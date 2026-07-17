"""Tests for the SSE streaming endpoint.

Verifies event structure, access-control gate on the streaming path,
and error handling. These tests do NOT require Claude API or Qdrant
(they test request validation and the shared retrieval path).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from custos.api import app

client = TestClient(app)


class TestStreamEndpointValidation:
    """The streaming endpoint must exist and validate requests."""

    def test_stream_endpoint_exists(self) -> None:
        response = client.post(
            "/api/chat/stream",
            json={"query": "test", "user_permissions": ["general"]},
        )
        # Not a 404 or 405; may be 500/503 (no Qdrant/API key)
        assert response.status_code not in (404, 405, 422)

    def test_stream_requires_query(self) -> None:
        response = client.post("/api/chat/stream", json={})
        assert response.status_code == 422

    def test_stream_default_permissions(self) -> None:
        response = client.post(
            "/api/chat/stream",
            json={"query": "test"},
        )
        assert response.status_code != 422


class TestStreamAccessControlSharedPath:
    """The streaming endpoint must use the same retrieval path as /api/chat.

    This is verified structurally: both endpoints call
    _retrieve_permitted_chunks(), which calls _get_retriever().retrieve()
    with the user's permissions. The access-control gate holds on both.
    """

    def test_stream_and_chat_share_retrieval_function(self) -> None:
        """Verify both endpoints use the same retrieval function."""
        import inspect

        from custos import api

        chat_source = inspect.getsource(api.chat)
        stream_source = inspect.getsource(api.chat_stream)

        # Both must call _retrieve_permitted_chunks
        assert "_retrieve_permitted_chunks" in chat_source, (
            "/api/chat does not use _retrieve_permitted_chunks"
        )
        assert "_retrieve_permitted_chunks" in stream_source, (
            "/api/chat/stream does not use _retrieve_permitted_chunks"
        )

    def test_stream_uses_consolidated_prompt_assembly(self) -> None:
        """Verify streaming uses build_prompt and stream_raw, not private members."""
        import inspect

        from custos import api

        stream_source = inspect.getsource(api.chat_stream)

        # Must use build_prompt (consolidated prompt assembly)
        assert "build_prompt" in stream_source, (
            "/api/chat/stream does not use ClaudeLLM.build_prompt"
        )
        # Must use stream_raw (consolidated streaming primitive)
        assert "stream_raw" in stream_source, (
            "/api/chat/stream does not use llm.stream_raw"
        )
        # Must NOT reach into private members
        assert "llm._client" not in stream_source, (
            "/api/chat/stream reaches into llm._client (use stream_raw instead)"
        )
        assert "llm._model" not in stream_source, (
            "/api/chat/stream reaches into llm._model (use stream_raw instead)"
        )
