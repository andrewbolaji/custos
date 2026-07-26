-- Migration 0001: chunks table for the pgvector VectorStore backend.
--
-- Applied explicitly via scripts/migrate_pgvector.py (tracked in
-- schema_migrations), never created lazily by PgVectorStore at request
-- time. See ADR-001 and docs/decisions/001-vector-store.md.
--
-- vector(384) matches BAAI/bge-small-en-v1.5 (LocalEmbedder.dimension).
-- If the embedder changes, this column width and a re-index both need to
-- change together -- it is not derived at runtime.
--
-- permissions carries the access-control list per chunk (mirrors the
-- Qdrant payload's "permissions" field). It is queried with the array
-- overlap operator (&&), which is fail-closed: an empty array overlaps
-- nothing, so an untagged chunk (or a user with no permissions) can never
-- match. See vector_store_pgvector.py:query for where this predicate is
-- built.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    text TEXT NOT NULL,
    section_path JSONB NOT NULL DEFAULT '[]',
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    permissions TEXT[] NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}',
    embedding vector(384) NOT NULL
);

CREATE INDEX chunks_doc_id_idx ON chunks (doc_id);

-- GIN index so the "permissions && $user_perms" predicate in the ACL
-- filter (query-time, not a post-filter) can use an index scan instead of
-- a sequential scan as the table grows.
CREATE INDEX chunks_permissions_gin_idx ON chunks USING gin (permissions);

-- HNSW index with the cosine operator class. This MUST match the distance
-- operator used in queries (<=> for cosine distance, backed by
-- vector_cosine_ops) -- Qdrant is configured with Distance.COSINE
-- (vector_store.py), and this keeps both backends comparable. A mismatched
-- operator class does not error; it silently falls back to a sequential
-- scan, which is why this is called out explicitly rather than left
-- implicit.
CREATE INDEX chunks_embedding_hnsw_idx ON chunks
    USING hnsw (embedding vector_cosine_ops);
