"""Postgres/pgvector vector store with server-side permission filtering.

Per ADR-001: pgvector is the documented alternate to Qdrant for deployments
that already run Postgres. Per the threat model (T5): access control is
enforced inside the SQL query that fetches candidates, never as a
post-filter in Python -- exactly the same invariant as the Qdrant path in
vector_store.py, just expressed as a WHERE clause instead of a Qdrant
payload filter.

Fail-closed rule (matches Qdrant): a chunk with no permissions, or a user
with no permissions, is retrievable by no one. Array overlap (&&) against
an empty array is always false in Postgres, so this falls out of the
predicate itself rather than needing a special-cased sentinel.

No ORM: every statement here is raw, parameterized SQL. Values (including
the ACL predicate's permission list) are always passed as query parameters,
never string-interpolated. The only string composition is psycopg.sql for
the table *identifier*, because identifiers cannot be parameterized with
%s placeholders -- that is a distinct mechanism from interpolating values
into the query text, and it is still injection-safe (psycopg quotes the
identifier).

Schema (table + HNSW index) is owned entirely by migrations/pgvector/ and
scripts/migrate_pgvector.py. This store never issues CREATE TABLE/INDEX at
request time -- see the migration file for why that's a deliberate choice.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from pgvector.psycopg import Vector, register_vector
from psycopg import sql
from psycopg.types.json import Jsonb

from custos.interfaces import Chunk, VectorStore

logger = logging.getLogger(__name__)

_DEFAULT_TABLE = "chunks"


class PgVectorStore(VectorStore):
    """Postgres-backed vector store with SQL WHERE filtering for access control."""

    def __init__(
        self,
        dsn: str,
        table_name: str = _DEFAULT_TABLE,
        vector_size: int = 384,
    ) -> None:
        self._dsn = dsn
        self._table = table_name
        self._vector_size = vector_size
        self._conn = psycopg.connect(dsn, autocommit=True)
        register_vector(self._conn)

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Insert or update chunks with their vectors."""
        if not chunks:
            return
        stmt = sql.SQL(
            """
            INSERT INTO {table}
                (chunk_id, doc_id, text, section_path, char_start, char_end,
                 permissions, metadata, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (chunk_id) DO UPDATE SET
                doc_id = EXCLUDED.doc_id,
                text = EXCLUDED.text,
                section_path = EXCLUDED.section_path,
                char_start = EXCLUDED.char_start,
                char_end = EXCLUDED.char_end,
                permissions = EXCLUDED.permissions,
                metadata = EXCLUDED.metadata,
                embedding = EXCLUDED.embedding
            """
        ).format(table=sql.Identifier(self._table))

        rows = [
            (
                chunk.chunk_id,
                chunk.doc_id,
                chunk.text,
                Jsonb(chunk.section_path),
                chunk.char_start,
                chunk.char_end,
                chunk.permissions,
                Jsonb(chunk.metadata),
                Vector(vector),
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        with self._conn.cursor() as cur:
            cur.executemany(stmt, rows)

    def count(self) -> int:
        """Return the number of rows in the table."""
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT count(*) FROM {table}").format(
                        table=sql.Identifier(self._table)
                    )
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0
        except Exception:
            return 0

    def query(
        self,
        vector: list[float],
        k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """Query for top-k similar chunks, filtered by permissions.

        The permission filter is part of the SAME SQL statement that does
        the ANN ordering and LIMIT -- it is a WHERE clause evaluated by
        Postgres while it picks candidate rows, not a filter applied to a
        Python list after fetching. That distinction matters: if the ACL
        predicate were applied after the LIMIT instead of before/alongside
        it, an over-fetch or a small k could return zero permitted rows
        even when permitted matches exist further down the ranking, or
        (worse) leak the wrong rows entirely under a naive
        fetch-then-filter refactor. Keeping it in the WHERE clause of the
        single query is what makes the ordering, the limit, and the ACL
        check atomic with respect to each other.

        All values (the query vector, the permission list, k) are bound as
        query parameters -- never interpolated into the SQL text. Only the
        table name uses psycopg.sql.Identifier, because identifiers cannot
        be bound as parameters at all.
        """
        where = sql.SQL("")
        params: list[Any] = []
        if filters is not None and "user_permissions" in filters:
            user_perms = [str(p) for p in filters["user_permissions"]]
            # Array overlap against the querying user's permissions. An
            # empty user_perms, or an empty/missing permissions column on
            # a chunk, can never overlap with anything -- fail-closed by
            # construction, matching QdrantVectorStore._build_filter.
            where = sql.SQL("WHERE permissions && %s")
            params.append(user_perms)

        stmt = sql.SQL(
            """
            SELECT chunk_id, doc_id, text, section_path, char_start, char_end,
                   permissions, metadata
            FROM {table}
            {where}
            ORDER BY embedding <=> %s
            LIMIT %s
            """
        ).format(table=sql.Identifier(self._table), where=where)
        params.append(Vector(vector))
        params.append(k)

        with self._conn.cursor() as cur:
            cur.execute(stmt, params)
            rows = cur.fetchall()

        return [self._row_to_chunk(row) for row in rows]

    def delete(self, chunk_ids: list[str]) -> None:
        """Remove chunks by their chunk_id."""
        if not chunk_ids:
            return
        stmt = sql.SQL("DELETE FROM {table} WHERE chunk_id = ANY(%s)").format(
            table=sql.Identifier(self._table)
        )
        with self._conn.cursor() as cur:
            cur.execute(stmt, (chunk_ids,))

    def recreate_collection(self) -> None:
        """Clear all rows for idempotent re-indexing.

        Unlike QdrantVectorStore.recreate_collection, this never drops or
        creates schema -- the table and its HNSW index are owned by
        migrations/pgvector/ (see scripts/migrate_pgvector.py), applied
        once, out of band. This only empties existing rows so `make index`
        can be re-run idempotently against either backend.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql.SQL("TRUNCATE TABLE {table}").format(table=sql.Identifier(self._table))
            )

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    @staticmethod
    def _row_to_chunk(row: tuple[Any, ...]) -> Chunk:
        (
            chunk_id,
            doc_id,
            text,
            section_path,
            char_start,
            char_end,
            permissions,
            metadata,
        ) = row
        return Chunk(
            chunk_id=str(chunk_id),
            doc_id=str(doc_id),
            text=str(text),
            section_path=list(section_path or []),
            char_start=int(char_start),
            char_end=int(char_end),
            permissions=list(permissions or []),
            metadata=dict(metadata or {}),
        )
