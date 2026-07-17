"""FastAPI service for Custos.

Endpoints:
    GET  /api/health         Liveness check
    POST /api/ingest         Trigger corpus indexing (admin action)
    POST /api/chat           Query the assistant (synchronous)
    POST /api/chat/stream    Query the assistant (streaming SSE)

DEMO SIMPLIFICATION: /api/chat and /api/chat/stream take user_permissions in
the request body. In production, permissions would come from an authenticated
identity (JWT, session, IdP), never from the request body, because a client
could claim any permissions. /api/ingest is also unauthenticated here. This is
a demo. Real auth is a Phase 4 deliverable. The honesty rule requires stating
this.

IMPORTANT: /api/chat/stream reuses the EXACT SAME retriever and permission
filter as /api/chat. Both endpoints call _retrieve_permitted_chunks(), which
calls _get_retriever().retrieve() with the user's permissions as a server-side
Qdrant filter. There is no parallel retrieval path. The access-control hard
gate holds on every endpoint that touches the corpus.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncGenerator
from dataclasses import asdict
from typing import Any

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from custos.embedder import LocalEmbedder
from custos.ingest import ingest_corpus
from custos.interfaces import Chunk
from custos.llm import ClaudeLLM, get_system_prompt
from custos.retriever import CustosRetriever
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

    This is the single retrieval path for both /api/chat and /api/chat/stream.
    The permission filter is applied inside the Qdrant query (server-side).
    """
    retriever = _get_retriever()
    return retriever.retrieve(query=query, user_permissions=user_permissions, k=5)


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

    Uses _retrieve_permitted_chunks() for access-controlled retrieval.
    """
    try:
        llm = _get_llm()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Service initialization failed")
        raise HTTPException(
            status_code=503, detail="Service unavailable. See server logs."
        ) from e

    try:
        chunks = _retrieve_permitted_chunks(request.query, request.user_permissions)
        answer = llm.generate(
            system_prompt=get_system_prompt(),
            context_chunks=chunks,
            user_query=request.query,
        )
    except Exception as e:
        logger.exception("Chat request failed")
        raise HTTPException(
            status_code=500, detail="Chat request failed. See server logs."
        ) from e

    return {
        "answer": answer.text,
        "citations": [asdict(c) for c in answer.citations],
        "refused": answer.refused,
    }


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest, http_request: Request) -> EventSourceResponse:
    """Query the assistant (streaming SSE).

    Uses the EXACT SAME _retrieve_permitted_chunks() as /api/chat.
    The access-control hard gate holds on this endpoint too.

    SSE events:
        event: token    data: {"text": "..."}
        event: citations data: {"citations": [...]}
        event: done     data: {}
        event: error    data: {"detail": "..."}
        event: refused  data: {"text": "I don't have information..."}
    """
    try:
        llm = _get_llm()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Service initialization failed")
        raise HTTPException(
            status_code=503, detail="Service unavailable. See server logs."
        ) from e

    try:
        chunks = _retrieve_permitted_chunks(request.query, request.user_permissions)
    except Exception as e:
        logger.exception("Retrieval failed")
        raise HTTPException(
            status_code=500, detail="Retrieval failed. See server logs."
        ) from e

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        # Empty context: refuse immediately
        if not chunks:
            yield {
                "event": "refused",
                "data": json.dumps({
                    "text": "I don't have information about that in the available documents."
                }),
            }
            yield {"event": "done", "data": "{}"}
            return

        chunk_lookup = {chunk.chunk_id: chunk for chunk in chunks}

        # Build context block (same as ClaudeLLM.generate)
        context_lines = []
        for chunk in chunks:
            context_lines.append(
                f"[chunk_id: {chunk.chunk_id}]\n"
                f"Source: {chunk.doc_id} > {' > '.join(chunk.section_path)}\n"
                f"{chunk.text}\n"
                f"---"
            )
        context_block = "\n".join(context_lines)
        full_system = get_system_prompt() + "\n" + context_block

        try:
            with llm._client.messages.stream(
                model=llm._model,
                max_tokens=llm._max_tokens,
                temperature=llm._temperature,
                system=full_system,
                messages=[{"role": "user", "content": request.query}],
            ) as stream:
                full_text = ""
                for text_chunk in stream.text_stream:
                    if await http_request.is_disconnected():
                        return
                    full_text += text_chunk
                    yield {
                        "event": "token",
                        "data": json.dumps({"text": text_chunk}),
                    }

            # Resolve citations from the full text
            cited_ids = ClaudeLLM._extract_citation_ids(full_text)
            citations = ClaudeLLM._resolve_citations(cited_ids, chunk_lookup)
            yield {
                "event": "citations",
                "data": json.dumps({
                    "citations": [asdict(c) for c in citations],
                }),
            }

        except anthropic.APIError:
            logger.exception("LLM streaming failed")
            yield {
                "event": "error",
                "data": json.dumps({"detail": "LLM request failed. See server logs."}),
            }

        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_generator())
