"""Permission-filtered retriever.

Embeds the user query, queries the vector store with the user's permissions as
a server-side filter, and returns the top-k permitted chunks. Access control
(T5) is enforced here, at retrieval, not in the prompt.
"""

from __future__ import annotations

from custos.interfaces import Chunk, Embedder, Retriever, VectorStore


class CustosRetriever(Retriever):
    """Retrieve relevant chunks scoped to the requesting user's permissions."""

    def __init__(self, embedder: Embedder, store: VectorStore) -> None:
        self._embedder = embedder
        self._store = store

    def retrieve(
        self,
        query: str,
        user_permissions: list[str],
        k: int = 5,
    ) -> list[Chunk]:
        """Embed the query and retrieve top-k permitted chunks.

        The permission filter is passed to the vector store, which applies it
        server-side inside the Qdrant query. No post-filtering in Python.
        """
        query_vector = self._embedder.embed([query])[0]
        return self._store.query(
            vector=query_vector,
            k=k,
            filters={"user_permissions": user_permissions},
        )
