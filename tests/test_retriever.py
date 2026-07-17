"""Tests for the permission-filtered retriever and vector store.

The access-control gate (T5) is a hard requirement: User A must retrieve
ZERO restricted chunks, not merely fewer. These tests use Qdrant's in-memory
mode (no Docker dependency for make test).

Fail-closed rule: chunks with empty or missing permissions are retrievable
by no one.
"""

from __future__ import annotations

from custos.interfaces import Chunk
from custos.vector_store import QdrantVectorStore

# A simple fake embedder for deterministic tests (no model download)
_DIM = 4


class _FakeEmbedder:
    """Deterministic embedder for testing. Maps text hash to a fixed vector."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            h = hash(text) % 1000
            vectors.append([h / 1000.0, (h + 1) / 1000.0, (h + 2) / 1000.0, (h + 3) / 1000.0])
        return vectors

    @property
    def dimension(self) -> int:
        return _DIM


def _make_store() -> QdrantVectorStore:
    return QdrantVectorStore(in_memory=True, vector_size=_DIM)


def _make_chunk(
    chunk_id: str,
    doc_id: str,
    text: str,
    permissions: list[str],
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        text=text,
        section_path=["Test"],
        char_start=0,
        char_end=len(text),
        permissions=permissions,
    )


class TestAccessControlHardGate:
    """User A must retrieve ZERO restricted chunks. Hard gate."""

    def setup_method(self) -> None:
        self.embedder = _FakeEmbedder()
        self.store = _make_store()
        self.store.ensure_collection()

        # Index three chunks with different permissions
        self.general_chunk = _make_chunk(
            "c-general", "faq-001", "How do I schedule a service call?", ["general"]
        )
        self.hr_chunk = _make_chunk(
            "c-hr", "hr-001", "Employee SSN: 900-55-0001", ["hr"]
        )
        self.finance_chunk = _make_chunk(
            "c-finance", "finance-001", "Net margin after overhead: 18%", ["finance", "owner"]
        )

        all_chunks = [self.general_chunk, self.hr_chunk, self.finance_chunk]
        vectors = self.embedder.embed([c.text for c in all_chunks])
        self.store.upsert(all_chunks, vectors)

    def test_general_user_gets_zero_hr_chunks(self) -> None:
        query_vec = self.embedder.embed(["employee SSN"])[0]
        results = self.store.query(
            vector=query_vec, k=10, filters={"user_permissions": ["general"]}
        )
        hr_results = [r for r in results if r.doc_id == "hr-001"]
        assert len(hr_results) == 0, f"General user retrieved HR chunks: {hr_results}"

    def test_general_user_gets_zero_finance_chunks(self) -> None:
        query_vec = self.embedder.embed(["net margin"])[0]
        results = self.store.query(
            vector=query_vec, k=10, filters={"user_permissions": ["general"]}
        )
        finance_results = [r for r in results if r.doc_id == "finance-001"]
        assert len(finance_results) == 0, (
            f"General user retrieved finance chunks: {finance_results}"
        )

    def test_hr_user_gets_hr_chunks(self) -> None:
        query_vec = self.embedder.embed(["employee SSN"])[0]
        results = self.store.query(
            vector=query_vec, k=10, filters={"user_permissions": ["hr", "general"]}
        )
        hr_results = [r for r in results if r.doc_id == "hr-001"]
        assert len(hr_results) == 1

    def test_hr_user_gets_zero_finance_chunks(self) -> None:
        query_vec = self.embedder.embed(["net margin"])[0]
        results = self.store.query(
            vector=query_vec, k=10, filters={"user_permissions": ["hr", "general"]}
        )
        finance_results = [r for r in results if r.doc_id == "finance-001"]
        assert len(finance_results) == 0

    def test_owner_gets_finance_chunks(self) -> None:
        query_vec = self.embedder.embed(["net margin"])[0]
        results = self.store.query(
            vector=query_vec, k=10, filters={"user_permissions": ["owner", "general"]}
        )
        finance_results = [r for r in results if r.doc_id == "finance-001"]
        assert len(finance_results) == 1

    def test_general_user_gets_general_chunks(self) -> None:
        query_vec = self.embedder.embed(["schedule service call"])[0]
        results = self.store.query(
            vector=query_vec, k=10, filters={"user_permissions": ["general"]}
        )
        general_results = [r for r in results if r.doc_id == "faq-001"]
        assert len(general_results) == 1


class TestFailClosedPermissions:
    """Chunks with empty or missing permissions are retrievable by no one."""

    def setup_method(self) -> None:
        self.embedder = _FakeEmbedder()
        self.store = _make_store()
        self.store.ensure_collection()

        # Chunk with empty permissions (untagged document)
        self.untagged_chunk = _make_chunk(
            "c-untagged", "untagged-001", "This document has no permission tags.", []
        )

        vectors = self.embedder.embed([self.untagged_chunk.text])
        self.store.upsert([self.untagged_chunk], vectors)

    def test_general_user_cannot_retrieve_untagged(self) -> None:
        query_vec = self.embedder.embed(["no permission tags"])[0]
        results = self.store.query(
            vector=query_vec, k=10, filters={"user_permissions": ["general"]}
        )
        assert len(results) == 0, "General user retrieved untagged chunk (fail open)"

    def test_hr_user_cannot_retrieve_untagged(self) -> None:
        query_vec = self.embedder.embed(["no permission tags"])[0]
        results = self.store.query(
            vector=query_vec, k=10, filters={"user_permissions": ["hr", "general"]}
        )
        assert len(results) == 0, "HR user retrieved untagged chunk (fail open)"

    def test_owner_cannot_retrieve_untagged(self) -> None:
        query_vec = self.embedder.embed(["no permission tags"])[0]
        results = self.store.query(
            vector=query_vec,
            k=10,
            filters={"user_permissions": ["owner", "general", "hr", "finance"]},
        )
        assert len(results) == 0, "Owner retrieved untagged chunk (fail open)"

    def test_empty_user_permissions_retrieves_nothing(self) -> None:
        """A user with no permissions can see nothing (fail closed)."""
        # Add a general chunk too
        general_chunk = _make_chunk(
            "c-general2", "faq-001", "General content here.", ["general"]
        )
        vectors = self.embedder.embed([general_chunk.text])
        self.store.upsert([general_chunk], vectors)

        query_vec = self.embedder.embed(["general content"])[0]
        results = self.store.query(
            vector=query_vec, k=10, filters={"user_permissions": []}
        )
        assert len(results) == 0, "User with no permissions retrieved chunks (fail open)"
