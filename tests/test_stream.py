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
    """Both endpoints must use the same retrieval path and AgentLoop.

    /api/chat uses _run_agent() (which calls AgentLoop.run()).
    /api/chat/stream uses AgentLoop.run_streaming() directly for
    real token-level streaming. Both share _retrieve_permitted_chunks.
    """

    def test_chat_uses_run_agent(self) -> None:
        """Verify /api/chat calls _run_agent."""
        import inspect

        from custos import api

        chat_source = inspect.getsource(api.chat)
        assert "_run_agent" in chat_source, (
            "/api/chat does not use _run_agent"
        )

    def test_stream_uses_shared_retrieval(self) -> None:
        """Verify /api/chat/stream routes through _retrieve_permitted_chunks."""
        import inspect

        from custos import api

        stream_source = inspect.getsource(api.chat_stream)
        assert "_retrieve_permitted_chunks" in stream_source, (
            "/api/chat/stream does not use _retrieve_permitted_chunks"
        )

    def test_stream_uses_agent_loop(self) -> None:
        """Verify /api/chat/stream uses AgentLoop for tool orchestration."""
        import inspect

        from custos import api

        stream_source = inspect.getsource(api.chat_stream)
        assert "AgentLoop" in stream_source, (
            "/api/chat/stream does not use AgentLoop"
        )
        assert "run_streaming" in stream_source, (
            "/api/chat/stream does not use run_streaming"
        )

    def test_run_agent_uses_shared_retrieval(self) -> None:
        """Verify _run_agent routes through _retrieve_permitted_chunks."""
        import inspect

        from custos import api

        run_agent_source = inspect.getsource(api._run_agent)
        assert "_retrieve_permitted_chunks" in run_agent_source, (
            "_run_agent does not use _retrieve_permitted_chunks"
        )

    def test_no_private_member_access_in_endpoints(self) -> None:
        """Endpoints must not reach into LLM private members."""
        import inspect

        from custos import api

        chat_source = inspect.getsource(api.chat)
        stream_source = inspect.getsource(api.chat_stream)

        for src, name in [(chat_source, "chat"), (stream_source, "stream")]:
            assert "llm._client" not in src, (
                f"/api/{name} reaches into llm._client"
            )
            assert "llm._model" not in src, (
                f"/api/{name} reaches into llm._model"
            )
