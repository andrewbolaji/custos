"""Apply pgvector migrations to CUSTOS_PGVECTOR_DSN.

Migrations live in migrations/pgvector/*.sql, numbered, applied in order.
Each applied filename is recorded in a schema_migrations table so re-runs
are idempotent -- but idempotent-via-tracking is not the same thing as
"create if not exists at runtime": the chunks table and its HNSW index are
only ever created here, by an explicit, reviewable migration step, never
lazily by PgVectorStore when it happens to get a query.

Usage:
    python scripts/migrate_pgvector.py
    make migrate-pgvector
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import psycopg

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations" / "pgvector"


def _pending_migrations(applied: set[str]) -> list[Path]:
    all_migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))
    return [m for m in all_migrations if m.name not in applied]


def run_migrations(dsn: str) -> list[str]:
    """Apply any not-yet-applied migration files. Returns names applied."""
    applied_now: list[str] = []
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute("SELECT filename FROM schema_migrations")
            already_applied = {row[0] for row in cur.fetchall()}
        conn.commit()

        for migration_path in _pending_migrations(already_applied):
            logger.info("Applying migration: %s", migration_path.name)
            sql = migration_path.read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)  # migration file content, not user input
                cur.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)",
                    (migration_path.name,),
                )
            conn.commit()
            applied_now.append(migration_path.name)

    return applied_now


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    dsn = os.environ.get("CUSTOS_PGVECTOR_DSN")
    if not dsn:
        print("CUSTOS_PGVECTOR_DSN is not set.", file=sys.stderr)
        return 1

    applied = run_migrations(dsn)
    if applied:
        logger.info("Applied %d migration(s): %s", len(applied), ", ".join(applied))
    else:
        logger.info("No pending migrations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
