"""FastAPI service for Custos.

Endpoints:
    GET  /api/health    Liveness check
    POST /api/ingest    Trigger corpus indexing (admin action)
    POST /api/chat      Query the assistant

DEMO SIMPLIFICATION: /api/chat takes user_permissions in the request body.
In production, permissions would come from an authenticated identity (JWT,
session, IdP), never from the request body, because a client could claim any
permissions. /api/ingest is also unauthenticated here. This is a demo. Real
auth is a Phase 4 deliverable. The honesty rule requires stating this.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from custos.embedder import LocalEmbedder
from custos.ingest import ingest_corpus
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
        raise HTTPException(status_code=503, detail=f"Ingest failed: {e}") from e
    return {"status": "ok", "chunks_indexed": len(chunks)}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> dict[str, Any]:
    """Query the assistant.

    DEMO SIMPLIFICATION: user_permissions comes from the request body.
    See ChatRequest docstring for the production path.
    """
    try:
        retriever = _get_retriever()
        llm = _get_llm()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Service initialization failed")
        raise HTTPException(status_code=503, detail=f"Service unavailable: {e}") from e

    try:
        chunks = retriever.retrieve(
            query=request.query,
            user_permissions=request.user_permissions,
            k=5,
        )

        answer = llm.generate(
            system_prompt=get_system_prompt(),
            context_chunks=chunks,
            user_query=request.query,
        )
    except Exception as e:
        logger.exception("Chat request failed")
        raise HTTPException(status_code=500, detail=f"Chat failed: {e}") from e

    return {
        "answer": answer.text,
        "citations": [asdict(c) for c in answer.citations],
        "refused": answer.refused,
    }
