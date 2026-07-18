"""FastAPI service for Custos.

Endpoints:
    GET  /api/health             Liveness check
    POST /api/ingest             Trigger corpus indexing (admin action)
    POST /api/chat               Query the assistant (synchronous)
    POST /api/chat/stream        Query the assistant (streaming SSE)
    POST /api/chat/confirm       Approve or reject a pending side-effectful action

DEMO SIMPLIFICATION: /api/chat and /api/chat/stream take user_permissions in
the request body. In production, permissions would come from an authenticated
identity (JWT, session, IdP), never from the request body, because a client
could claim any permissions. /api/ingest is also unauthenticated here. This is
a demo. Real auth is a Phase 4 deliverable. The honesty rule requires stating
this.

The access-control hard gate holds on every path that touches the corpus,
including corpus-touching tools (search_documents, summarize_section) which
route through the permission-filtered retriever.
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import json
import logging
import os
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from custos.agent_loop import AgentLoop, AgentResult
from custos.boot import ensure_index_ready
from custos.embedder import LocalEmbedder
from custos.ingest import ingest_corpus
from custos.injection_detector import InjectionDetector
from custos.interfaces import Chunk
from custos.llm import ClaudeLLM, get_refusal_text, get_system_prompt
from custos.pending_actions import PendingActionStore
from custos.pii import PIIRedactor
from custos.rate_limiter import RateLimiter
from custos.retriever import CustosRetriever
from custos.tool_registry import ToolRegistry
from custos.tools.file_ticket import FileTicketTool
from custos.tools.search_documents import SearchDocumentsTool
from custos.tools.send_email import SendEmailTool
from custos.tools.summarize_section import SummarizeSectionTool
from custos.vector_store import QdrantVectorStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PII log scrubbing (threat T4): redact the FINAL formatted output
# ---------------------------------------------------------------------------
# A logging.Filter on the root logger does NOT work: Python calls
# ancestor HANDLERS on propagation, never ancestor logger filters.
# And redacting record.msg misses PII passed as %s args.
#
# Solution: a Formatter subclass that redacts the result of
# super().format(), catching msg + args + exception tracebacks.
# We install it by wrapping every handler's formatter.
# ---------------------------------------------------------------------------
_log_redactor = PIIRedactor()


class PIIFormatter(logging.Formatter):
    """Wraps another formatter and redacts PII from the final output."""

    def __init__(self, inner: logging.Formatter | None = None) -> None:
        super().__init__()
        self._inner = inner or logging.Formatter()

    def format(self, record: logging.LogRecord) -> str:
        formatted = self._inner.format(record)
        return _log_redactor.redact(formatted)


def _install_pii_formatter() -> None:
    """Wrap every handler's formatter with PIIFormatter across ALL loggers.

    Iterates the root logger AND every named logger (including
    uvicorn.access, uvicorn.error) so the guarantee covers every
    handler, not just the application's own loggers.

    Called at import time and again at startup (via the lifespan
    event) to catch handlers configured by uvicorn after import.
    """
    seen: set[int] = set()

    def _wrap_handlers(lgr: logging.Logger) -> None:
        for handler in lgr.handlers:
            hid = id(handler)
            if hid in seen:
                continue
            seen.add(hid)
            if not isinstance(handler.formatter, PIIFormatter):
                handler.setFormatter(PIIFormatter(handler.formatter))

    root = logging.getLogger()
    _wrap_handlers(root)

    # Wrap handlers on all named loggers (uvicorn.error, uvicorn.access, etc.)
    for name in list(logging.Logger.manager.loggerDict):
        lgr = logging.getLogger(name)
        if isinstance(lgr, logging.Logger):
            _wrap_handlers(lgr)

    # If root still has no handlers, add one so early calls are covered
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(PIIFormatter())
        root.addHandler(handler)


_install_pii_formatter()


@asynccontextmanager
async def _lifespan(app_instance: FastAPI) -> AsyncGenerator[None, None]:
    """Startup: PII formatter, index verification."""
    global _index_ready, _index_chunks, _index_expected  # noqa: PLW0603
    _install_pii_formatter()

    # Verify/rebuild the index before reporting healthy
    try:
        embedder = _get_embedder()
        store = _get_store()
        _index_chunks, _index_expected = ensure_index_ready(embedder, store)
        _index_ready = _index_chunks == _index_expected and _index_chunks > 0
        logger.info("Boot: index %s, %d/%d chunks",
                     "ready" if _index_ready else "INCOMPLETE",
                     _index_chunks, _index_expected)
    except Exception:
        logger.exception("Boot: index check failed")
        _index_ready = False

    yield


app = FastAPI(
    title="Custos API",
    description=(
        "Private AI assistant that answers from a business's own documents. "
        "DEMO: user_permissions in the request body is a simplification. "
        "In production, permissions come from an authenticated identity."
    ),
    version="0.1.0",
    lifespan=_lifespan,
)

# CORS: configurable for production (UI origin only).
# Default allows local dev origins.
_cors_origins = os.environ.get(
    "CUSTOS_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Shared components (initialized lazily)
# ---------------------------------------------------------------------------

_embedder: LocalEmbedder | None = None
_store: QdrantVectorStore | None = None
_retriever: CustosRetriever | None = None
_llm: ClaudeLLM | None = None
_pending_actions = PendingActionStore()
_injection_detector = InjectionDetector()
_rate_limiter = RateLimiter()
_index_ready = False
_index_chunks = 0
_index_expected = 0

# Admin token: must be set in the environment. Never in the repo.
_ADMIN_TOKEN = os.environ.get("CUSTOS_ADMIN_TOKEN", "")

# Conversation memory: last N messages (sliding window)
MAX_HISTORY_MESSAGES = 20


def _trim_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """Trim history to the last MAX_HISTORY_MESSAGES entries.

    History is untrusted client input (like user_permissions). It
    provides conversational context but does not bypass any security
    control. Retrieval, PII redaction, and tool gating all apply
    per turn regardless of history content.
    """
    valid = [
        m for m in history
        if isinstance(m, dict)
        and m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str)
    ]
    return valid[-MAX_HISTORY_MESSAGES:]


def _get_embedder() -> LocalEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = LocalEmbedder()
    return _embedder


def _get_store() -> QdrantVectorStore:
    global _store
    if _store is None:
        qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
        collection = os.environ.get("QDRANT_COLLECTION", "custos")
        _store = QdrantVectorStore(
            url=qdrant_url,
            collection_name=collection,
            vector_size=_get_embedder().dimension,
        )
    return _store


def _get_retriever() -> CustosRetriever:
    global _retriever
    if _retriever is None:
        _retriever = CustosRetriever(embedder=_get_embedder(), store=_get_store())
    return _retriever


def _get_llm() -> ClaudeLLM:
    global _llm
    if _llm is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="ANTHROPIC_API_KEY not configured. The LLM is unavailable.",
            )
        _llm = ClaudeLLM(api_key=api_key)
    return _llm


# Whether to trust X-Forwarded-For (only behind a trusted reverse proxy).
# Off by default; production compose sets CUSTOS_TRUST_PROXY=1.
_TRUST_PROXY = os.environ.get("CUSTOS_TRUST_PROXY", "").lower() in ("1", "true", "yes")


def _get_client_ip(request: Request) -> str:
    """Extract the real client IP.

    When CUSTOS_TRUST_PROXY is set, reads X-Forwarded-For (Caddy sets
    it from the TCP remote address; the client cannot forge it because
    Caddy overwrites the header). Otherwise uses the direct socket.
    """
    if _TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


def _check_rate_limit(request: Request, query: str, session_id: str) -> str | None:
    """Check all rate limits. Returns None if allowed, or an error message.

    Does NOT record. Recording happens at the point the model call is
    committed (after retrieval returns chunks, before the LLM call).
    Both /api/chat and /api/chat/stream call _rate_limiter.record_request
    at that point.
    """
    client_ip = _get_client_ip(request)
    return _rate_limiter.check_request(client_ip, session_id, len(query))


def _retrieve_permitted_chunks(query: str, user_permissions: list[str]) -> list[Chunk]:
    """Retrieve chunks using the shared retriever with permission filtering.

    This is the single retrieval path for all corpus access, including
    corpus-touching tools. The permission filter is applied inside the
    Qdrant query (server-side).
    """
    retriever = _get_retriever()
    return retriever.retrieve(query=query, user_permissions=user_permissions, k=5)


def _retrieve_and_scan(
    query: str, user_permissions: list[str]
) -> tuple[list[Chunk], bool]:
    """Retrieve chunks, scan for injections, and return sanitized chunks.

    Returns (sanitized_chunks, injection_detected). The source documents
    are never modified; only the prompt copies have matched spans replaced
    with a neutral placeholder.
    """
    chunks = _retrieve_permitted_chunks(query, user_permissions)
    if not chunks:
        return chunks, False
    result = _injection_detector.scan(chunks)
    if result.detected:
        logger.info(
            "Injection detected: %d span(s) sanitized in retrieved chunks",
            result.count,
        )
    return result.sanitized_chunks, result.detected


def _build_registry(user_permissions: list[str]) -> ToolRegistry:
    """Build a tool registry scoped to the current user's permissions.

    Corpus-touching tools (search_documents, summarize_section) receive
    the user's permissions and route through the SAME permission-filtered
    retriever. Side-effectful tools (send_email, file_ticket) are always
    simulated and gated by the PendingAction confirmation flow.
    """
    retriever = _get_retriever()
    registry = ToolRegistry()
    registry.register(SearchDocumentsTool(retriever, user_permissions))
    registry.register(SummarizeSectionTool(retriever, user_permissions))
    registry.register(SendEmailTool())
    registry.register(FileTicketTool())
    return registry


def _run_agent(
    query: str,
    user_permissions: list[str],
    history: list[dict[str, str]] | None = None,
    chunks: list[Chunk] | None = None,
) -> AgentResult:
    """Run the agent loop. Used by BOTH /api/chat and /api/chat/stream.

    If chunks are provided (pre-retrieved and sanitized), uses them
    directly. Otherwise retrieves fresh (backward compatible).
    """
    llm = _get_llm()
    if chunks is None:
        chunks = _retrieve_permitted_chunks(query, user_permissions)

    if not chunks:
        return AgentResult(
            text=get_refusal_text(),
            citations=[],
            refused=True,
            events=[],
            tool_results=[],
        )

    parts = ClaudeLLM.build_prompt(get_system_prompt(), chunks)
    registry = _build_registry(user_permissions)
    loop = AgentLoop(llm=llm, registry=registry)
    return loop.run(parts, query, history=history)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """Chat request.

    DEMO SIMPLIFICATION: user_permissions comes from the request body.
    In production, this would be derived from the authenticated user's
    identity (JWT claims, IdP groups, database lookup), never from the
    client. A client could claim ["hr", "finance", "owner"] and access
    everything. This is documented, not hidden.
    """

    query: str
    user_permissions: list[str] = ["general"]
    session_id: str = ""
    history: list[dict[str, str]] = []


class CitationResponse(BaseModel):
    doc_id: str
    doc_name: str
    section_path: list[str]
    char_start: int
    char_end: int
    snippet: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]
    refused: bool


class ConfirmRequest(BaseModel):
    """Approve or reject a pending side-effectful action."""

    action_id: str
    session_id: str
    approved: bool


class ConfirmResponse(BaseModel):
    status: str  # "executed", "rejected", "error"
    tool_name: str = ""
    output: str = ""
    simulated: bool = False


class IngestResponse(BaseModel):
    status: str
    chunks_indexed: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict[str, str]:
    """Public health check. Returns status only, no internal details."""
    return {"status": "ok" if _index_ready else "degraded"}


@app.get("/api/admin/status")
def admin_status(request: Request) -> dict[str, Any]:
    """Admin status endpoint. Returns 404 on wrong/missing token
    (does not leak whether the route exists). Rate-limited like
    all other routes.
    """
    auth = request.headers.get("authorization", "")
    expected = f"Bearer {_ADMIN_TOKEN}"
    if not _ADMIN_TOKEN or not secrets.compare_digest(auth, expected):
        raise HTTPException(status_code=404)

    rate_status = _rate_limiter.get_status()
    return {
        "status": "ok" if _index_ready else "degraded",
        "index_ready": _index_ready,
        "chunks": _index_chunks,
        "expected_chunks": _index_expected,
        "qdrant_connected": _store is not None,
        "model": os.environ.get("CUSTOS_MODEL", "claude-sonnet-4-6"),
        **rate_status,
    }


@app.post("/api/ingest", response_model=IngestResponse)
def ingest() -> dict[str, Any]:
    """Trigger corpus indexing.

    DEMO SIMPLIFICATION: unauthenticated. In production, this would
    require admin credentials.
    """
    try:
        embedder = _get_embedder()
        store = _get_store()
        store.recreate_collection()
        chunks = ingest_corpus(embedder=embedder, store=store)
    except Exception as e:
        logger.exception("Ingest failed")
        raise HTTPException(
            status_code=503, detail="Ingest failed. See server logs."
        ) from e
    return {"status": "ok", "chunks_indexed": len(chunks)}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest, http_request: Request) -> dict[str, Any]:
    """Query the assistant (synchronous)."""
    limit_msg = _check_rate_limit(http_request, request.query, request.session_id)
    if limit_msg:
        raise HTTPException(status_code=429, detail=limit_msg)

    try:
        _get_llm()  # Fail fast if no API key
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Service initialization failed")
        raise HTTPException(
            status_code=503, detail="Service unavailable. See server logs."
        ) from e

    try:
        trimmed = _trim_history(request.history)
        chunks, _detected = _retrieve_and_scan(request.query, request.user_permissions)
        # Record at model-call commitment (after retrieval, before LLM)
        if chunks:
            _rate_limiter.record_request(request.session_id)
        result = _run_agent(
            request.query, request.user_permissions, history=trimmed, chunks=chunks
        )
    except Exception as e:
        logger.exception("Chat request failed")
        raise HTTPException(
            status_code=500, detail="Chat request failed. See server logs."
        ) from e

    return {
        "answer": result.text,
        "citations": [asdict(c) for c in result.citations],
        "refused": result.refused,
    }


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest, http_request: Request) -> EventSourceResponse:
    """Query the assistant (streaming SSE).

    Uses AgentLoop.run_streaming() for real token-level streaming.
    Each text delta is emitted as an SSE token event as it arrives
    from Claude, giving fast time-to-first-token.

    SSE events:
        event: token      data: {"text": "..."}
        event: citations   data: {"citations": [...]}
        event: tool_use    data: {"tool_name": "...", "simulated": false}
        event: done        data: {}
        event: error       data: {"detail": "..."}
        event: refused     data: {"text": "I don't have information..."}
    """
    limit_msg = _check_rate_limit(http_request, request.query, request.session_id)
    if limit_msg:
        raise HTTPException(status_code=429, detail=limit_msg)

    try:
        _get_llm()  # Fail fast if no API key
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Service initialization failed")
        raise HTTPException(
            status_code=503, detail="Service unavailable. See server logs."
        ) from e

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        llm = _get_llm()

        # Milestone 1: retrieval + injection scan
        yield {
            "event": "status",
            "data": json.dumps({"text": "Searching documents"}),
        }

        chunks, injection_detected = _retrieve_and_scan(
            request.query, request.user_permissions
        )

        if not chunks:
            yield {
                "event": "refused",
                "data": json.dumps({"text": get_refusal_text()}),
            }
            yield {"event": "done", "data": "{}"}
            return

        # Milestone 2: retrieval complete, report real count
        yield {
            "event": "status",
            "data": json.dumps({
                "text": f"Reading {len(chunks)} excerpt{'s' if len(chunks) != 1 else ''}",
            }),
        }

        # Emit guardrail event if injection was detected and sanitized
        if injection_detected:
            yield {
                "event": "guardrail",
                "data": json.dumps({"type": "injection_blocked"}),
            }

        # Record at model-call commitment (after retrieval, before LLM).
        # Cost is incurred from this point regardless of client disconnect.
        _rate_limiter.record_request(request.session_id)

        parts = ClaudeLLM.build_prompt(get_system_prompt(), chunks)
        registry = _build_registry(request.user_permissions)
        loop = AgentLoop(llm=llm, registry=registry)
        trimmed = _trim_history(request.history)

        try:
            stream_iter = loop.run_streaming(
                parts,
                request.query,
                session_id=request.session_id,
                pending_store=_pending_actions,
                history=trimmed,
            )
            for event in stream_iter:
                # Stop streaming if the client disconnected
                if await http_request.is_disconnected():
                    logger.info("Client disconnected, stopping stream")
                    break
                if event.kind == "text_delta":
                    yield {
                        "event": "token",
                        "data": json.dumps({"text": event.data.get("text", "")}),
                    }
                elif event.kind == "text_replace":
                    # Reconciliation: resolve_response produced different
                    # text than what was streamed. Replace displayed text.
                    yield {
                        "event": "text_replace",
                        "data": json.dumps({"text": event.data.get("text", "")}),
                    }
                elif event.kind == "tool_use":
                    # tool_use fires when a read-only tool starts executing.
                    # We emit a single SSE event here; the tool_result event
                    # (which follows) is NOT emitted as a second SSE to avoid
                    # doubled tool badges in the UI.
                    yield {
                        "event": "tool_use",
                        "data": json.dumps({
                            "tool_name": event.data.get("tool_name", ""),
                        }),
                    }
                elif event.kind == "tool_result":
                    # Intentionally not emitted as a separate SSE event.
                    # The tool_use event above already notified the frontend.
                    pass
                elif event.kind == "confirm_action":
                    yield {
                        "event": "confirm_action",
                        "data": json.dumps({
                            "tool_name": event.data.get("tool_name", ""),
                            "action_id": event.data.get("action_id", ""),
                            "arguments": event.data.get("arguments", {}),
                        }),
                    }
                elif event.kind == "citations":
                    yield {
                        "event": "citations",
                        "data": json.dumps({
                            "citations": [
                                asdict(c) for c in event.data.get("citations", [])
                            ],
                        }),
                    }
                elif event.kind == "refused":
                    yield {
                        "event": "refused",
                        "data": json.dumps({"text": event.data.get("text", "")}),
                    }
                elif event.kind == "limit_hit":
                    yield {
                        "event": "error",
                        "data": json.dumps({
                            "detail": "Request exceeded processing limits.",
                        }),
                    }
        except anthropic.APITimeoutError:
            logger.warning("Anthropic API timed out for query: %s", request.query[:50])
            yield {
                "event": "error",
                "data": json.dumps({
                    "detail": "The service timed out. Please try again.",
                }),
            }
        except anthropic.APIConnectionError:
            logger.warning("Anthropic API connection failed for query: %s", request.query[:50])
            yield {
                "event": "error",
                "data": json.dumps({
                    "detail": "Could not connect to the AI service. Please try again.",
                }),
            }
        except Exception:
            logger.exception("Agent loop failed")
            yield {
                "event": "error",
                "data": json.dumps({
                    "detail": "Something went wrong. Please try again.",
                }),
            }

        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_generator())


@app.post("/api/chat/confirm", response_model=ConfirmResponse)
def confirm_action(request: ConfirmRequest) -> dict[str, Any]:
    """Approve or reject a pending side-effectful action.

    Security invariants:
    - Action ID is unguessable (uuid4). Cannot enumerate others' actions.
    - Session binding: only the session that created the action can confirm.
    - TTL: expired actions are rejected.
    - One-shot: each action can only be confirmed/rejected once.
    """
    action = _pending_actions.consume(request.action_id)
    if action is None:
        raise HTTPException(
            status_code=404,
            detail="Action not found, already processed, or expired.",
        )

    if action.expired:
        raise HTTPException(
            status_code=410,
            detail="Action has expired. Please try again.",
        )

    if action.session_id != request.session_id:
        logger.warning(
            "Session mismatch for action %s: expected %s, got %s",
            request.action_id,
            action.session_id,
            request.session_id,
        )
        raise HTTPException(
            status_code=403,
            detail="Session mismatch. This action belongs to a different session.",
        )

    # Clean up other expired actions opportunistically
    _pending_actions.cleanup_expired()

    if not request.approved:
        return {
            "status": "rejected",
            "tool_name": action.tool_name,
            "output": "Action was rejected by the user.",
        }

    # Execute the tool (always simulated for now)
    registry = _build_registry(["general"])
    tool = registry.get(action.tool_name)
    if tool is None:
        raise HTTPException(
            status_code=404,
            detail=f"Tool '{action.tool_name}' not found.",
        )

    try:
        result = tool.run(action.arguments)
    except Exception as e:
        logger.exception("Tool execution failed during confirm: %s", action.tool_name)
        raise HTTPException(
            status_code=500,
            detail="Tool execution failed. See server logs.",
        ) from e

    return {
        "status": "executed",
        "tool_name": result.tool_name,
        "output": str(result.output),
        "simulated": result.simulated,
    }
