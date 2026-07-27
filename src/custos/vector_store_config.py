"""Vector store backend selection.

CUSTOS_VECTOR_BACKEND picks between "qdrant" (default) and "pgvector". This
module is the only place backend-specific construction happens; retrieval
code (retriever.py, CustosRetriever) depends only on the VectorStore
interface and never imports a concrete backend directly.

AdminVectorStore is a small, explicit union of the two concrete backends,
used only by infra/lifecycle call sites (ingest.py, boot.py, api.py) that
need recreate_collection()/count()/ping() -- operations that are
deliberately NOT part of the VectorStore ABC (interfaces.py). VectorStore is
the retrieval contract (upsert/query/delete); clearing a store for
idempotent re-indexing, polling its row count, or checking live
reachability is an admin concern that only a couple of call sites need, and
QdrantVectorStore already exposed count()/recreate_collection() as plain
extra methods beyond the ABC before pgvector existed. ping() joined them for
the same reason: count() deliberately swallows every exception and returns
0 on failure (ensure_index_ready needs 0 to mean "needs reindexing", not
"unreachable"), so it cannot serve callers -- wait_for_qdrant, api.py's
_check_store_connected() -- that need to tell those two states apart.
Widening VectorStore to add any of these would leak an ingest/ops-only
concern into the interface every retrieval-path caller depends on, so it
stays a union of concrete types instead.
"""

from __future__ import annotations

import os

from custos.vector_store import QdrantVectorStore
from custos.vector_store_pgvector import PgVectorStore

AdminVectorStore = QdrantVectorStore | PgVectorStore

_BACKENDS = ("qdrant", "pgvector")


def get_vector_store(vector_size: int) -> AdminVectorStore:
    """Construct the VectorStore backend selected by CUSTOS_VECTOR_BACKEND.

    The return type is the concrete-type union (not VectorStore) because
    every current call site needs the admin methods too. Code that only
    needs retrieval (CustosRetriever) accepts VectorStore and is handed
    the same instance, upcast implicitly.
    """
    backend = os.environ.get("CUSTOS_VECTOR_BACKEND", "qdrant").strip().lower()

    if backend == "qdrant":
        url = os.environ.get("QDRANT_URL", "http://localhost:6333")
        collection = os.environ.get("QDRANT_COLLECTION", "custos")
        return QdrantVectorStore(url=url, collection_name=collection, vector_size=vector_size)

    if backend == "pgvector":
        dsn = os.environ.get("CUSTOS_PGVECTOR_DSN")
        # Strip whitespace: a trailing newline in the DSN breaks the
        # connection string the same way an unstripped API key breaks the
        # Anthropic client -- fails downstream in libpq/psycopg2 instead of
        # here, further from the actual cause.
        if dsn is not None:
            dsn = dsn.strip()
        if not dsn:
            raise RuntimeError(
                "CUSTOS_VECTOR_BACKEND=pgvector requires CUSTOS_PGVECTOR_DSN to be set."
            )
        return PgVectorStore(dsn=dsn, vector_size=vector_size)

    raise ValueError(
        f"Unknown CUSTOS_VECTOR_BACKEND={backend!r}; expected one of {_BACKENDS}."
    )
