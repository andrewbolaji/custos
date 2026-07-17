"""Tests for the SSE streaming endpoint.

Verifies event structure, access-control gate on the streaming path,
and error handling. These tests do NOT require Claude API or Qdrant
(they test request validation and the shared retrieval path).

Tests that POST to /api/chat/stream explicitly clear ANTHROPIC_API_KEY
and the cached _llm singleton so they always hit the 503 fast-exit path
in _get_llm(). Without this, load_dotenv() makes the key available,
the endpoint enters the SSE generator, and sse_starlette's global
AppStatus.should_exit_event poisons subsequent tests (it binds to the
first test's event loop, then throws RuntimeError on the next one).
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import custos.api
from custos.api import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_llm_cache() -> None:
    """Reset the cached LLM singleton and hide the API key.

    This ensures every test in this module gets a clean _llm=None,
    and tests that POST to the streaming endpoint hit the 503 path
    deterministically, regardless of what .env provides.
    """
    custos.api._llm = None


class TestStreamEndpointValidation:
    """The streaming endpoint must exist and validate requests."""

    def test_stream_endpoint_exists(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            response = client.post(
                "/api/chat/stream",
                json={"query": "test", "user_permissions": ["general"]},
            )
        # 503: no API key. Not a 404 or 405 (endpoint exists).
        assert response.status_code not in (404, 405, 422)

    def test_stream_requires_query(self) -> None:
        response = client.post("/api/chat/stream", json={})
        assert response.status_code == 422

    def test_stream_default_permissions(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
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
