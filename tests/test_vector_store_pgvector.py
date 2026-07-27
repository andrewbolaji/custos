"""Tests for the pgvector-backed VectorStore and its access-control query.

Mirrors tests/test_retriever.py's Qdrant hard-gate tests but against
PgVectorStore, plus a dedicated proof that the ACL predicate is
parameterized: a permission value containing SQL metacharacters must be
treated as inert data, never executed as SQL.

Unlike the Qdrant tests, there is no in-memory pgvector mode, so this
module needs a real reachable Postgres (with the vector extension
available). It skips (not fails) when that isn't available, the same way
evals/suites/retrieval.py skips without a running Qdrant -- `make
test`/`make check` stay green on a clean tree with no Docker running.

These tests run against their OWN table (`chunks_pgvector_test`), created
and torn down by this module, never the migration-owned `chunks` table
that real corpus data lives in (migrations/pgvector/0001_create_chunks.sql,
scripts/migrate_pgvector.py). An earlier version of this suite ran against
the shared `chunks` table and truncated it as test setup/teardown, which
silently wiped out real indexed corpus data run against the same DSN --
a test-isolation bug, not a store bug. Creating a scratch table here is
test scaffolding, not the "no create-if-not-exists at runtime" rule the
store itself follows -- that rule is about the shipped store never doing
DDL against the app's real schema, not about tests managing their own
sandbox.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import psycopg
import pytest
from psycopg import sql

from custos.interfaces import Chunk
from custos.vector_store_pgvector import PgVectorStore

if TYPE_CHECKING:
    from collections.abc import Generator

# Matches vector(384) in migrations/pgvector/0001_create_chunks.sql (BGE-small).
_DIM = 384
_TEST_DSN = os.environ.get(
    "CUSTOS_PGVECTOR_TEST_DSN",
    "postgresql://postgres:localdev@localhost:5433/custos",
)
_TEST_TABLE = "chunks_pgvector_test"


def _pgvector_ready() -> bool:
    """True if the DSN is reachable at all. Schema is this module's own concern."""
    try:
        with psycopg.connect(_TEST_DSN, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pgvector_ready(),
    reason=(
        f"pgvector not reachable at {_TEST_DSN}; run `docker compose up -d pgvector`"
    ),
)


@pytest.fixture(scope="module", autouse=True)
def _test_table() -> Generator[None]:
    """Create this module's isolated scratch table, drop it afterward.

    Mirrors migrations/pgvector/0001_create_chunks.sql's column set (minus
    the HNSW index, which these functional/security tests don't exercise)
    under a name that can never collide with the real chunks table.
    """
    with psycopg.connect(_TEST_DSN) as conn, conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {table} (
                    chunk_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    section_path JSONB NOT NULL DEFAULT '[]',
                    char_start INTEGER NOT NULL,
                    char_end INTEGER NOT NULL,
                    permissions TEXT[] NOT NULL DEFAULT '{{}}',
                    metadata JSONB NOT NULL DEFAULT '{{}}',
                    embedding vector(384) NOT NULL
                )
                """
            ).format(table=sql.Identifier(_TEST_TABLE))
        )
        conn.commit()
    yield
    with psycopg.connect(_TEST_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("DROP TABLE IF EXISTS {table}").format(table=sql.Identifier(_TEST_TABLE))
        )
        conn.commit()


def _make_chunk(chunk_id: str, doc_id: str, text: str, permissions: list[str]) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        text=text,
        section_path=["Test"],
        char_start=0,
        char_end=len(text),
        permissions=permissions,
    )


def _vec(seed: int) -> list[float]:
    """A deterministic 384-dim vector, distinguishable by seed."""
    return [((seed * 37 + i) % 1000) / 1000.0 for i in range(_DIM)]


@pytest.fixture
def store() -> Generator[PgVectorStore]:
    """A PgVectorStore against this module's isolated test table, cleared
    before use -- never the real chunks table (see module docstring)."""
    s = PgVectorStore(dsn=_TEST_DSN, table_name=_TEST_TABLE, vector_size=_DIM)
    s.recreate_collection()  # truncates rows only; schema untouched
    yield s
    s.recreate_collection()
    s.close()


class TestAccessControlHardGate:
    """User A must retrieve ZERO restricted chunks. Hard gate, same as Qdrant."""

    def test_general_user_gets_zero_hr_chunks(self, store: PgVectorStore) -> None:
        store.upsert(
            [
                _make_chunk("c1", "d1", "general info", ["general"]),
                _make_chunk("c2", "d2", "hr salary data", ["hr"]),
            ],
            [_vec(1), _vec(2)],
        )
        results = store.query(_vec(1), k=10, filters={"user_permissions": ["general"]})
        assert {c.chunk_id for c in results} == {"c1"}

    def test_hr_user_gets_zero_finance_chunks(self, store: PgVectorStore) -> None:
        store.upsert(
            [
                _make_chunk("c1", "d1", "hr data", ["hr"]),
                _make_chunk("c2", "d2", "finance data", ["finance"]),
            ],
            [_vec(1), _vec(2)],
        )
        results = store.query(_vec(1), k=10, filters={"user_permissions": ["hr"]})
        assert {c.chunk_id for c in results} == {"c1"}

    def test_multi_permission_user_gets_union(self, store: PgVectorStore) -> None:
        store.upsert(
            [
                _make_chunk("c1", "d1", "general", ["general"]),
                _make_chunk("c2", "d2", "hr", ["hr"]),
                _make_chunk("c3", "d3", "finance", ["finance"]),
            ],
            [_vec(1), _vec(2), _vec(3)],
        )
        results = store.query(_vec(1), k=10, filters={"user_permissions": ["general", "hr"]})
        assert {c.chunk_id for c in results} == {"c1", "c2"}


class TestFailClosedPermissions:
    """Chunks with empty permissions, or users with none, retrieve nothing."""

    def test_untagged_chunk_never_retrieved(self, store: PgVectorStore) -> None:
        store.upsert([_make_chunk("c1", "d1", "untagged", [])], [_vec(1)])
        results = store.query(_vec(1), k=10, filters={"user_permissions": ["general"]})
        assert results == []

    def test_empty_user_permissions_retrieves_nothing(self, store: PgVectorStore) -> None:
        store.upsert([_make_chunk("c1", "d1", "general", ["general"])], [_vec(1)])
        results = store.query(_vec(1), k=10, filters={"user_permissions": []})
        assert results == []

    def test_no_filters_key_is_unfiltered_not_denied(self, store: PgVectorStore) -> None:
        """filters=None (or missing the key) means 'no restriction requested',
        distinct from an empty permissions list meaning 'no access'. Matches
        QdrantVectorStore._build_filter's documented behavior."""
        store.upsert([_make_chunk("c1", "d1", "general", ["general"])], [_vec(1)])
        results = store.query(_vec(1), k=10, filters=None)
        assert {c.chunk_id for c in results} == {"c1"}


class TestSQLInjectionResistance:
    """The ACL predicate is parameterized SQL, never string interpolation.

    A permission value (or chunk_id) containing SQL metacharacters must be
    treated purely as data: it neither breaks the query nor lets a user
    craft a permission string that widens what they can see.
    """

    def test_metacharacter_permission_is_treated_as_data(self, store: PgVectorStore) -> None:
        evil = "general' OR '1'='1"
        store.upsert(
            [
                _make_chunk("c1", "d1", "safe doc", ["general"]),
                _make_chunk("c2", "d2", "evil-tagged doc", [evil]),
            ],
            [_vec(1), _vec(2)],
        )

        # Querying with the exact metacharacter string as the user's own
        # permission retrieves only the chunk tagged with that literal
        # string -- proving it was matched as an opaque value, not
        # executed or used to alter the WHERE clause's logic.
        results = store.query(_vec(1), k=10, filters={"user_permissions": [evil]})
        assert {c.chunk_id for c in results} == {"c2"}

        # A normal user permission does not "leak" into matching the evil
        # row (which it would if the string were somehow unescaped into an
        # always-true OR clause).
        results = store.query(_vec(1), k=10, filters={"user_permissions": ["general"]})
        assert {c.chunk_id for c in results} == {"c1"}

        # The table is still intact and both rows are present.
        assert store.count() == 2

    def test_metacharacter_chunk_id_round_trips_safely(self, store: PgVectorStore) -> None:
        evil_id = "c1'); DROP TABLE chunks; --"
        store.upsert([_make_chunk(evil_id, "d1", "doc", ["general"])], [_vec(1)])
        assert store.count() == 1

        results = store.query(_vec(1), k=10, filters={"user_permissions": ["general"]})
        assert [c.chunk_id for c in results] == [evil_id]

        store.delete([evil_id])
        assert store.count() == 0

    def test_metacharacter_in_delete_targets_only_matching_row(
        self, store: PgVectorStore
    ) -> None:
        store.upsert(
            [
                _make_chunk("c1", "d1", "doc", ["general"]),
                _make_chunk("c2", "d2", "doc", ["general"]),
            ],
            [_vec(1), _vec(2)],
        )
        store.delete(["c1' OR '1'='1"])  # matches nothing; must not delete everything
        assert store.count() == 2


class TestUpsertIsIdempotent:
    def test_upsert_same_chunk_id_updates_in_place(self, store: PgVectorStore) -> None:
        store.upsert([_make_chunk("c1", "d1", "v1", ["general"])], [_vec(1)])
        store.upsert([_make_chunk("c1", "d1", "v2", ["hr"])], [_vec(2)])
        assert store.count() == 1

        results = store.query(_vec(2), k=10, filters={"user_permissions": ["hr"]})
        assert len(results) == 1
        assert results[0].text == "v2"

        results = store.query(_vec(2), k=10, filters={"user_permissions": ["general"]})
        assert results == []


class TestPingCountContractSplit:
    """count() swallows every exception and returns 0 on failure by design
    (ensure_index_ready needs 0 to mean "needs reindexing", not
    "unreachable"). ping() exists specifically for callers -- api.py's
    _check_store_connected(), boot.py's wait_for_qdrant -- that need the
    real reachability signal instead. This runs against the real class, not
    a mock, so it verifies psycopg's actual behavior rather than a test
    double's assumption about it.

    Uses its own PgVectorStore instances, closed within each test, rather
    than the shared `store` fixture -- that fixture's teardown calls
    recreate_collection() after yielding, which would raise against a
    connection a test already closed.
    """

    def test_ping_succeeds_against_a_reachable_connection(self) -> None:
        """Load-bearing, not a decorative sanity check: this is what keeps
        test_ping_raises_after_connection_is_closed below honest. Without
        this test, deleting or renaming ping() would still pass that one
        (AttributeError satisfies a bare `pytest.raises(Exception)`); this
        one would catch it.
        """
        s = PgVectorStore(dsn=_TEST_DSN, table_name=_TEST_TABLE, vector_size=_DIM)
        try:
            s.ping()  # must not raise
        finally:
            s.close()

    def test_ping_raises_after_connection_is_closed(self) -> None:
        s = PgVectorStore(dsn=_TEST_DSN, table_name=_TEST_TABLE, vector_size=_DIM)
        s.close()
        # Deliberately broad: pinning psycopg's specific exception type here
        # would make this test track that library's internals rather than
        # the contract this file cares about (raises vs. swallows).
        with pytest.raises(Exception):  # noqa: B017, PT011 -- psycopg's own exception type
            s.ping()

    def test_count_swallows_and_returns_zero_after_connection_is_closed(self) -> None:
        s = PgVectorStore(dsn=_TEST_DSN, table_name=_TEST_TABLE, vector_size=_DIM)
        s.close()
        assert s.count() == 0
