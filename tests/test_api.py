"""FastAPI endpoint integration tests.

Tests the API endpoints using httpx TestClient. These tests do NOT require
Qdrant or Claude API to be running (they test the endpoint wiring and
request/response shapes, not the full pipeline).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from custos.api import app

client = TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("ok", "degraded")


class TestChatEndpointValidation:
    def test_chat_requires_query(self) -> None:
        response = client.post("/api/chat", json={})
        assert response.status_code == 422  # Pydantic validation

    def test_chat_accepts_valid_request(self) -> None:
        # This will fail with a connection error (no Qdrant/Claude),
        # but it validates the request parsing works
        response = client.post(
            "/api/chat",
            json={"query": "What is the PTO policy?", "user_permissions": ["general"]},
        )
        # We expect a 500 (no Qdrant) or 503 (no API key), not a 422
        assert response.status_code != 422

    def test_chat_default_permissions(self) -> None:
        # user_permissions defaults to ["general"]
        response = client.post(
            "/api/chat",
            json={"query": "test"},
        )
        assert response.status_code != 422


class TestIngestEndpointValidation:
    def test_ingest_endpoint_exists(self) -> None:
        # Will fail with 500 (connection error to Qdrant) but proves
        # the endpoint exists and is wired correctly
        response = client.post("/api/ingest")
        # Not a 404 or 405 (endpoint exists); 500 is expected (no Qdrant)
        assert response.status_code not in (404, 405, 422)
