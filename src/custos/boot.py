"""Boot-time index verification and idempotent reindexing.

Checks the Qdrant collection's point count against the expected
count derived from the corpus manifest. Reindexes on any mismatch
(zero, partial, or stale), not only on zero.

The expected count is computed from the manifest at boot time, not
hardcoded. If the corpus changes, the expected count changes and
the index is rebuilt on next restart.
"""

from __future__ import annotations

import logging

from custos.chunker import chunk_document
from custos.embedder import LocalEmbedder
from custos.ingest import CORPUS_DIR, ingest_corpus, load_manifest
from custos.vector_store import QdrantVectorStore

logger = logging.getLogger(__name__)


def compute_expected_chunks() -> int:
    """Compute the expected chunk count from the corpus manifest.

    Runs the chunker on every document (same as ingest). Takes a few
    seconds; cache the result after the first call.
    """
    docs = load_manifest(CORPUS_DIR)
    total = 0
    for doc_meta in docs:
        doc_id = str(doc_meta["doc_id"])
        doc_file = str(doc_meta["file"])
        raw_perms = doc_meta.get("permissions", [])
        perms = [str(p) for p in raw_perms] if isinstance(raw_perms, list) else []
        text = (CORPUS_DIR / doc_file).read_text(encoding="utf-8")
        chunks = chunk_document(text=text, doc_id=doc_id, permissions=perms)
        total += len(chunks)
    return total


def ensure_index_ready(
    embedder: LocalEmbedder,
    store: QdrantVectorStore,
) -> tuple[int, int]:
    """Verify the index is complete; reindex if not.

    Returns (actual_count, expected_count). The caller should consider
    the index ready only when actual == expected.
    """
    expected = compute_expected_chunks()
    logger.info("Expected chunk count from manifest: %d", expected)

    try:
        actual = store.count()
    except Exception:
        logger.warning("Could not query Qdrant; assuming index missing")
        actual = 0

    if actual == expected:
        logger.info("Index verified: %d/%d chunks present", actual, expected)
        return actual, expected

    if actual > 0:
        logger.warning(
            "Index mismatch: %d/%d chunks. Reindexing.", actual, expected
        )
    else:
        logger.info("Index empty. Building from corpus.")

    ingest_corpus(corpus_dir=CORPUS_DIR, embedder=embedder, store=store)

    try:
        final = store.count()
    except Exception:
        final = 0

    logger.info("Reindex complete: %d chunks indexed", final)
    return final, expected
