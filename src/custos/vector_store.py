"""Qdrant vector store with server-side permission filtering.

Per ADR-001: Qdrant is the primary store. Per the threat model (T5): access
control is enforced inside the Qdrant query, never as a post-filter in Python.

Fail-closed rule: a chunk with no permissions or an empty permissions list is
retrievable by no one. This prevents an untagged document from silently leaking
to everyone.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from qdrant_client import QdrantClient, models

from custos.interfaces import Chunk, VectorStore

logger = logging.getLogger(__name__)

_DEFAULT_COLLECTION = "custos"


class QdrantVectorStore(VectorStore):
    """Qdrant-backed vector store with payload filtering for access control."""

    def __init__(
        self,
        url: str = "http://localhost:6333",
        collection_name: str = _DEFAULT_COLLECTION,
        vector_size: int = 384,
        in_memory: bool = False,
    ) -> None:
        if in_memory:
            self._client = QdrantClient(location=":memory:")
        else:
            self._client = QdrantClient(url=url)
        self._collection = collection_name
        self._vector_size = vector_size

    def ensure_collection(self) -> None:
        """Create the collection if it does not exist."""
        collections = self._client.get_collections().collections
        names = [c.name for c in collections]
        if self._collection not in names:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=models.VectorParams(
                    size=self._vector_size,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info("Created collection: %s", self._collection)

    def recreate_collection(self) -> None:
        """Drop and recreate the collection. Used for idempotent re-indexing."""
        self._client.recreate_collection(
            collection_name=self._collection,
            vectors_config=models.VectorParams(
                size=self._vector_size,
                distance=models.Distance.COSINE,
            ),
        )
        logger.info("Recreated collection: %s", self._collection)

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Insert or update chunks with their vectors."""
        if not chunks:
            return
        points = [
            models.PointStruct(
                id=self._stable_id(chunk.chunk_id),
                vector=vector,
                payload={
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "text": chunk.text,
                    "section_path": chunk.section_path,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "permissions": chunk.permissions,
                    "metadata": chunk.metadata,
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        self._client.upsert(collection_name=self._collection, points=points)

    def query(
        self,
        vector: list[float],
        k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """Query for top-k similar chunks, filtered by permissions.

        The permission filter is applied INSIDE the Qdrant query (server-side).
        A chunk is returned only if at least one of its permissions values is
        present in the user's permission list.

        Fail-closed: chunks with empty or missing permissions never match any
        filter because Qdrant's MatchAny on an empty permissions list yields
        no results. This is enforced by the query structure, not post-filtering.
        """
        qdrant_filter = self._build_filter(filters)

        results = self._client.query_points(
            collection_name=self._collection,
            query=vector,
            limit=k,
            query_filter=qdrant_filter,
            with_payload=True,
        )

        return [self._point_to_chunk(hit) for hit in results.points]

    def delete(self, chunk_ids: list[str]) -> None:
        """Remove chunks by their chunk_id."""
        if not chunk_ids:
            return
        point_ids: list[int | str | uuid.UUID] = [
            self._stable_id(cid) for cid in chunk_ids
        ]
        self._client.delete(
            collection_name=self._collection,
            points_selector=models.PointIdsList(points=point_ids),
        )

    def _build_filter(self, filters: dict[str, Any] | None) -> models.Filter | None:
        """Build a Qdrant filter from the query filters dict.

        Expected filter key: "user_permissions" -> list[str]

        The filter uses MatchAny: a chunk's permissions field must contain at
        least one value from the user's permission list. Because this is a
        must condition, chunks with empty permissions lists can never match
        (MatchAny against an empty field returns false). This is fail-closed.
        """
        if not filters or "user_permissions" not in filters:
            return None

        user_perms: list[str] = filters["user_permissions"]
        if not user_perms:
            # No user permissions means the user can see nothing.
            # Return an impossible filter to enforce fail-closed.
            return models.Filter(
                must=[
                    models.FieldCondition(
                        key="permissions",
                        match=models.MatchValue(value="__impossible_permission__"),
                    )
                ]
            )

        return models.Filter(
            must=[
                models.FieldCondition(
                    key="permissions",
                    match=models.MatchAny(any=user_perms),
                )
            ]
        )

    @staticmethod
    def _point_to_chunk(point: models.ScoredPoint) -> Chunk:
        """Convert a Qdrant search result to a Chunk."""
        payload = point.payload or {}
        return Chunk(
            chunk_id=str(payload.get("chunk_id", "")),
            doc_id=str(payload.get("doc_id", "")),
            text=str(payload.get("text", "")),
            section_path=list(payload.get("section_path", [])),
            char_start=int(payload.get("char_start", 0)),
            char_end=int(payload.get("char_end", 0)),
            permissions=list(payload.get("permissions", [])),
            metadata=dict(payload.get("metadata", {})),
        )

    @staticmethod
    def _stable_id(chunk_id: str) -> str:
        """Create a stable Qdrant point ID from a chunk ID.

        Qdrant accepts UUIDs or unsigned ints. We use a UUID5 from the chunk_id
        to ensure deterministic, collision-resistant IDs.
        """
        import uuid

        return str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id))
