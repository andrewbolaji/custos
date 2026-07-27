"""FastAPI endpoint integration tests.

Tests the API endpoints using httpx TestClient. These tests do NOT require
Qdrant or Claude API to be running (they test the endpoint wiring and
request/response shapes, not the full pipeline).
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

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
        original_recheck = api_module._last_recheck
        try:
            api_module._index_ready = False
            # Suppress self-heal re-check by pretending one just happened
            api_module._last_recheck = time.monotonic()
            response = client.get("/api/health")
            assert response.status_code == 503
            assert response.json() == {"status": "degraded"}
        finally:
            api_module._index_ready = original
            api_module._last_recheck = original_recheck

    def test_openapi_documents_503_and_200_responses(self) -> None:
        """The responses= metadata on /api/health should actually show up
        in the generated OpenAPI schema, not just exist as dead documentation.

        FastAPI emits a bare "200" entry for any GET route regardless of
        this metadata, so asserting "200" is present alone would pass even
        if _HEALTH_RESPONSES were deleted -- assert on content that can only
        come from _HEALTH_RESPONSES specifically.
        """
        schema = client.get("/openapi.json").json()
        responses = schema["paths"]["/api/health"]["get"]["responses"]
        assert responses["200"]["description"] == "Index ready."
        assert responses["503"]["description"] == "Index not ready."
        ok_example = responses["200"]["content"]["application/json"]["example"]
        degraded_example = responses["503"]["content"]["application/json"]["example"]
        assert ok_example == {"status": "ok"}
        assert degraded_example == {"status": "degraded"}


class TestAdminStatusEndpoint:
    def test_admin_status_stays_200_when_index_not_ready(self) -> None:
        """Deliberate asymmetry: /api/health is a probe (503 while degraded),
        /api/admin/status is a diagnostic that must stay readable precisely
        when the system is degraded, so it always returns 200 once
        authenticated.
        """
        original_ready = api_module._index_ready
        original_recheck = api_module._last_recheck
        original_token = api_module._ADMIN_TOKEN
        try:
            api_module._index_ready = False
            api_module._last_recheck = time.monotonic()
            api_module._ADMIN_TOKEN = "test-token"  # noqa: S105 -- test fixture, not a real credential
            response = client.get(
                "/api/admin/status",
                headers={"Authorization": "Bearer test-token"},
            )
            assert response.status_code == 200
            assert response.json()["status"] == "degraded"
            assert response.json()["index_ready"] is False
        finally:
            api_module._index_ready = original_ready
            api_module._last_recheck = original_recheck
            api_module._ADMIN_TOKEN = original_token

    def test_qdrant_connected_is_false_after_boot_when_store_is_dead(self) -> None:
        """qdrant_connected must be a live probe, not `_store is not None`.

        A task can boot successfully (index_ready stays True -- nothing in
        the request path resets it) and then lose its vector store later.
        qdrant_connected has to catch that even though index_ready cannot.
        The double's `ping()` raises -- both real VectorStore backends'
        `count()` swallow every exception and return 0 instead of raising
        (see vector_store.py / vector_store_pgvector.py), so a double built
        on `count.side_effect = ConnectionError(...)` would test a contract
        no real store has; `ping()` is the method that actually raises.
        """
        original_ready = api_module._index_ready
        original_token = api_module._ADMIN_TOKEN
        try:
            api_module._index_ready = True
            api_module._ADMIN_TOKEN = "test-token"  # noqa: S105 -- test fixture, not a real credential
            dead_store = MagicMock()
            dead_store.ping.side_effect = ConnectionError("refused")
            with patch.object(api_module, "_store", dead_store):
                response = client.get(
                    "/api/admin/status",
                    headers={"Authorization": "Bearer test-token"},
                )
            assert response.status_code == 200
            assert response.json()["index_ready"] is True
            assert response.json()["qdrant_connected"] is False
        finally:
            api_module._index_ready = original_ready
            api_module._ADMIN_TOKEN = original_token

    def test_qdrant_connected_is_true_when_store_responds(self) -> None:
        original_token = api_module._ADMIN_TOKEN
        try:
            api_module._ADMIN_TOKEN = "test-token"  # noqa: S105 -- test fixture, not a real credential
            live_store = MagicMock()
            live_store.ping.return_value = None
            with patch.object(api_module, "_store", live_store):
                response = client.get(
                    "/api/admin/status",
                    headers={"Authorization": "Bearer test-token"},
                )
            assert response.json()["qdrant_connected"] is True
        finally:
            api_module._ADMIN_TOKEN = original_token

    def test_qdrant_connected_ignores_count_and_uses_ping(self) -> None:
        """A store whose count() swallows an outage and returns 0 (the real
        contract -- see vector_store.py) must still be reported disconnected
        if ping() raises, and connected if ping() succeeds even though the
        collection is empty. Guards against reintroducing a count()-based
        probe that can't tell "unreachable" from "reachable but empty".
        """
        original_token = api_module._ADMIN_TOKEN
        try:
            api_module._ADMIN_TOKEN = "test-token"  # noqa: S105 -- test fixture, not a real credential

            unreachable_but_zero = MagicMock()
            unreachable_but_zero.count.return_value = 0  # count()'s real swallow contract
            unreachable_but_zero.ping.side_effect = ConnectionError("refused")
            with patch.object(api_module, "_store", unreachable_but_zero):
                response = client.get(
                    "/api/admin/status",
                    headers={"Authorization": "Bearer test-token"},
                )
            assert response.json()["qdrant_connected"] is False

            reachable_but_empty = MagicMock()
            reachable_but_empty.count.return_value = 0  # genuinely empty collection
            reachable_but_empty.ping.return_value = None
            with patch.object(api_module, "_store", reachable_but_empty):
                response = client.get(
                    "/api/admin/status",
                    headers={"Authorization": "Bearer test-token"},
                )
            assert response.json()["qdrant_connected"] is True
        finally:
            api_module._ADMIN_TOKEN = original_token


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
                api_module, "_get_llm", return_value=MagicMock(),
            ), patch.object(
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
                api_module, "_get_llm", return_value=MagicMock(),
            ), patch.object(
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
