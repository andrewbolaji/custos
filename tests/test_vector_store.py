"""Tests for QdrantVectorStore's ping()/count() contract split.

count() swallows every exception and returns 0 on failure by design
(ensure_index_ready needs 0 to mean "needs reindexing", not "unreachable").
ping() exists specifically for callers that need the real reachability
signal -- see the ping() docstrings in vector_store.py and
vector_store_pgvector.py, and _check_store_connected() / wait_for_qdrant in
api.py / boot.py, which both depend on ping() actually raising rather than
swallowing.

This runs against a real QdrantVectorStore pointed at a closed local port,
not a mock, so it verifies the actual client library's behavior rather than
a test double's assumption about it. No Docker or running Qdrant required:
binding a socket and closing it immediately yields a port nothing is
listening on.
"""

from __future__ import annotations

import socket

import pytest

from custos.vector_store import QdrantVectorStore


def _unused_port() -> int:
    """A local TCP port nothing is listening on."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


@pytest.fixture
def unreachable_store() -> QdrantVectorStore:
    return QdrantVectorStore(url=f"http://127.0.0.1:{_unused_port()}")


class TestPingCountContractSplit:
    def test_count_swallows_and_returns_zero_when_unreachable(
        self, unreachable_store: QdrantVectorStore
    ) -> None:
        assert unreachable_store.count() == 0

    def test_ping_raises_when_unreachable(self, unreachable_store: QdrantVectorStore) -> None:
        # Deliberately broad: pinning qdrant_client's specific exception
        # type here would make this test track that library's internals
        # rather than the contract this file cares about (raises vs.
        # swallows). test_ping_succeeds_against_a_reachable_store below is
        # what keeps this honest -- it fails if ping() is deleted, renamed,
        # or made to always raise.
        with pytest.raises(Exception):  # noqa: B017, PT011 -- real client's exception type, not ours to pin
            unreachable_store.ping()

    def test_ping_succeeds_against_a_reachable_store(self) -> None:
        """Load-bearing, not a decorative sanity check: this is what keeps
        test_ping_raises_when_unreachable above honest. Without this test,
        deleting or renaming ping() would still pass that one (AttributeError
        satisfies a bare `pytest.raises(Exception)`); this one would catch it.
        """
        store = QdrantVectorStore(in_memory=True, vector_size=8)
        store.ping()  # must not raise
