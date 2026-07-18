"""FastAPI endpoint integration tests.

Tests the API endpoints using httpx TestClient. These tests do NOT require
Qdrant or Claude API to be running (they test the endpoint wiring and
request/response shapes, not the full pipeline).
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

import custos.api as api_module
from custos.api import app

client = TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok_when_index_ready(self) -> None:
        original = api_module._index_ready
        try:
            api_module._index_ready = True
            response = client.get("/api/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
        finally:
            api_module._index_ready = original

    def test_health_returns_degraded_when_index_not_ready(self) -> None:
        original = api_module._index_ready
        try:
            api_module._index_ready = False
            response = client.get("/api/health")
            assert response.status_code == 200
            assert response.json() == {"status": "degraded"}
        finally:
            api_module._index_ready = original


class TestReadinessGate:
    """Chat endpoints must return 503 when the index is not ready."""

    def test_chat_returns_503_when_not_ready(self) -> None:
        original = api_module._index_ready
        try:
            api_module._index_ready = False
            response = client.post(
                "/api/chat",
                json={"query": "test", "user_permissions": ["general"]},
            )
            assert response.status_code == 503
            assert "temporarily unavailable" in response.json()["detail"].lower()
        finally:
            api_module._index_ready = original

    def test_stream_returns_503_when_not_ready(self) -> None:
        original = api_module._index_ready
        try:
            api_module._index_ready = False
            response = client.post(
                "/api/chat/stream",
                json={"query": "test", "user_permissions": ["general"]},
            )
            assert response.status_code == 503
            assert "temporarily unavailable" in response.json()["detail"].lower()
        finally:
            api_module._index_ready = original

    def test_503_does_not_call_model(self) -> None:
        """When index is not ready, _get_llm must never be called."""
        original = api_module._index_ready
        try:
            api_module._index_ready = False
            with patch.object(api_module, "_get_llm") as mock_llm:
                client.post(
                    "/api/chat",
                    json={"query": "test"},
                )
                mock_llm.assert_not_called()
        finally:
            api_module._index_ready = original


class TestRetrievalConnectionError:
    """A Qdrant connection failure mid-request must return a clean 503."""

    def test_retrieval_failure_returns_503(self) -> None:
        original = api_module._index_ready
        try:
            api_module._index_ready = True
            with patch.object(
                api_module, "_retrieve_permitted_chunks",
                side_effect=ConnectionError("Qdrant refused connection"),
            ):
                response = client.post(
                    "/api/chat",
                    json={"query": "test"},
                )
                assert response.status_code == 503
                data = response.json()
                assert "temporarily unavailable" in data["detail"].lower()
                # Must NOT expose internal details
                assert "qdrant" not in data["detail"].lower()
                assert "connection" not in data["detail"].lower()
        finally:
            api_module._index_ready = original


class TestStreamRetrievalFailure:
    """A Qdrant failure in the streaming path must emit a clean notice
    event, not an unhandled exception in a 200 response.
    """

    def test_stream_retrieval_failure_emits_notice(self) -> None:
        original = api_module._index_ready
        try:
            api_module._index_ready = True
            with patch.object(
                api_module, "_retrieve_permitted_chunks",
                side_effect=ConnectionError("Qdrant refused connection"),
            ):
                response = client.post(
                    "/api/chat/stream",
                    json={"query": "test"},
                )
                # Response is 200 (SSE) -- the error is in the event stream
                assert response.status_code == 200
                body = response.text

                # Must contain the clean unavailable message
                assert "temporarily unavailable" in body.lower()

                # Must NOT contain internal details
                assert "qdrant" not in body.lower()
                assert "connection" not in body.lower()
                assert "Traceback" not in body

                # Must terminate with a done event
                assert '"done"' in body or "event: done" in body
        finally:
            api_module._index_ready = original


class TestChatEndpointValidation:
    def test_chat_requires_query(self) -> None:
        response = client.post("/api/chat", json={})
        assert response.status_code == 422  # Pydantic validation

    def test_chat_accepts_valid_request(self) -> None:
        response = client.post(
            "/api/chat",
            json={"query": "What is the PTO policy?", "user_permissions": ["general"]},
        )
        assert response.status_code != 422

    def test_chat_default_permissions(self) -> None:
        response = client.post(
            "/api/chat",
            json={"query": "test"},
        )
        assert response.status_code != 422


class TestIngestEndpointValidation:
    def test_ingest_endpoint_exists(self) -> None:
        response = client.post("/api/ingest")
        assert response.status_code not in (404, 405, 422)
