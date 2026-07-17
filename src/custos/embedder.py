"""Local embedder using BGE-small-en-v1.5.

Documents never leave the deployment. Per ADR-002: local embeddings are the
default, and the Embedder interface makes the provider swappable.
"""

from __future__ import annotations

import logging
from typing import Any

from custos.interfaces import Embedder

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


class LocalEmbedder(Embedder):
    """Embed text locally using sentence-transformers.

    The model is loaded on first use and cached in memory. The weights are
    downloaded on first run (~130MB) and cached by huggingface_hub.
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model: Any = None

    def _load_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading embedding model: %s", self._model_name)
            self._model = SentenceTransformer(self._model_name)
            dim = self._model.get_sentence_embedding_dimension()
            logger.info("Embedding model loaded (dim=%d)", dim)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using the local model. Returns one vector per input."""
        if not texts:
            return []
        model = self._load_model()
        embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [vec.tolist() for vec in embeddings]

    @property
    def dimension(self) -> int:
        """Return the embedding dimension."""
        model = self._load_model()
        dim: int = model.get_sentence_embedding_dimension()
        return dim
