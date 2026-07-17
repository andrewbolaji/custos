"""Corpus ingest pipeline.

Reads the corpus manifest, loads each document, chunks it, embeds the chunks,
and upserts them to Qdrant. Idempotent: re-running recreates the collection.

Usage:
    python -m custos.ingest           # from the command line
    POST /api/ingest                  # via the API (admin action)
    make index                        # via Makefile
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from custos.chunker import chunk_document
from custos.embedder import LocalEmbedder
from custos.interfaces import Chunk, Embedder
from custos.vector_store import QdrantVectorStore

logger = logging.getLogger(__name__)

CORPUS_DIR = Path(__file__).parent.parent.parent / "corpus" / "output"
BATCH_SIZE = 32


def load_manifest(corpus_dir: Path = CORPUS_DIR) -> list[dict[str, object]]:
    """Load the corpus manifest."""
    manifest_path = corpus_dir / "manifest.yaml"
    with open(manifest_path) as f:
        manifest = yaml.safe_load(f)
    return list(manifest["documents"])


def ingest_corpus(
    corpus_dir: Path = CORPUS_DIR,
    embedder: Embedder | None = None,
    store: QdrantVectorStore | None = None,
) -> list[Chunk]:
    """Ingest the corpus: chunk, embed, and upsert to the vector store.

    Returns all chunks for inspection/testing.
    """
    if embedder is None:
        embedder = LocalEmbedder()
    if store is None:
        store = QdrantVectorStore()

    docs = load_manifest(corpus_dir)
    logger.info("Ingesting %d documents from %s", len(docs), corpus_dir)

    # Recreate collection for idempotent re-indexing
    store.recreate_collection()

    all_chunks: list[Chunk] = []

    for doc_meta in docs:
        doc_id = str(doc_meta["doc_id"])
        doc_file = str(doc_meta["file"])
        raw_perms = doc_meta.get("permissions", [])
        permissions = [str(p) for p in raw_perms] if isinstance(raw_perms, list) else []

        file_path = corpus_dir / doc_file
        text = file_path.read_text(encoding="utf-8")

        chunks = chunk_document(
            text=text,
            doc_id=doc_id,
            permissions=permissions,
            metadata={"doc_name": str(doc_meta.get("title", doc_id))},
        )
        all_chunks.extend(chunks)
        logger.info(
            "  %s: %d chunks (permissions: %s)",
            doc_id,
            len(chunks),
            permissions,
        )

    # Embed and upsert in batches
    logger.info("Embedding %d chunks...", len(all_chunks))
    for i in range(0, len(all_chunks), BATCH_SIZE):
        batch = all_chunks[i : i + BATCH_SIZE]
        texts = [c.text for c in batch]
        vectors = embedder.embed(texts)
        store.upsert(batch, vectors)
        logger.info("  Upserted batch %d-%d", i, i + len(batch))

    logger.info("Ingest complete: %d chunks indexed", len(all_chunks))
    return all_chunks


def main() -> None:
    """Run ingest from the command line."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    ingest_corpus()


if __name__ == "__main__":
    main()
