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

import json
import logging
import os
from collections.abc import AsyncGenerator
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from custos.agent_loop import AgentLoop, AgentResult
from custos.embedder import LocalEmbedder
from custos.ingest import ingest_corpus
from custos.interfaces import Chunk
from custos.llm import ClaudeLLM, get_refusal_text, get_system_prompt
from custos.pending_actions import PendingActionStore
from custos.retriever import CustosRetriever
from custos.tool_registry import ToolRegistry
from custos.tools.file_ticket import FileTicketTool
from custos.tools.search_documents import SearchDocumentsTool
from custos.tools.send_email import SendEmailTool
from custos.tools.summarize_section import SummarizeSectionTool
from custos.vector_store import QdrantVectorStore

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Custos API",
    description=(
        "Private AI assistant that answers from a business's own documents. "
        "DEMO: user_permissions in the request body is a simplification. "
        "In production, permissions come from an authenticated identity."
    ),
    version="0.1.0",
)

# CORS for local dev (Vite on :5173, API on :8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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


def _retrieve_permitted_chunks(query: str, user_permissions: list[str]) -> list[Chunk]:
    """Retrieve chunks using the shared retriever with permission filtering.

    This is the single retrieval path for all corpus access, including
    corpus-touching tools. The permission filter is applied inside the
    Qdrant query (server-side).
    """
    retriever = _get_retriever()
    return retriever.retrieve(query=query, user_permissions=user_permissions, k=5)


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


def _run_agent(query: str, user_permissions: list[str]) -> AgentResult:
    """Run the agent loop. Used by BOTH /api/chat and /api/chat/stream.

    This is the single agent-loop entry point, mirroring how both endpoints
    previously shared _retrieve_permitted_chunks() and build_prompt().
    """
    llm = _get_llm()
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
    return loop.run(parts, query)


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
    return {"status": "ok"}


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
def chat(request: ChatRequest) -> dict[str, Any]:
    """Query the assistant (synchronous).

    Uses _run_agent() which calls the same _retrieve_permitted_chunks()
    and AgentLoop as /api/chat/stream.
    """
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
        result = _run_agent(request.query, request.user_permissions)
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
        chunks = _retrieve_permitted_chunks(request.query, request.user_permissions)

        if not chunks:
            yield {
                "event": "refused",
                "data": json.dumps({"text": get_refusal_text()}),
            }
            yield {"event": "done", "data": "{}"}
            return

        parts = ClaudeLLM.build_prompt(get_system_prompt(), chunks)
        registry = _build_registry(request.user_permissions)
        loop = AgentLoop(llm=llm, registry=registry)

        try:
            stream_iter = loop.run_streaming(
                parts,
                request.query,
                session_id=request.session_id,
                pending_store=_pending_actions,
            )
            for event in stream_iter:
                if event.kind == "text_delta":
                    yield {
                        "event": "token",
                        "data": json.dumps({"text": event.data.get("text", "")}),
                    }
                elif event.kind == "tool_use":
                    yield {
                        "event": "tool_use",
                        "data": json.dumps({
                            "tool_name": event.data.get("tool_name", ""),
                        }),
                    }
                elif event.kind == "tool_result":
                    yield {
                        "event": "tool_use",
                        "data": json.dumps({
                            "tool_name": event.data.get("tool_name", ""),
                            "simulated": event.data.get("simulated", False),
                        }),
                    }
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
        except Exception:
            logger.exception("Agent loop failed")
            yield {
                "event": "error",
                "data": json.dumps({"detail": "Chat request failed. See server logs."}),
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
