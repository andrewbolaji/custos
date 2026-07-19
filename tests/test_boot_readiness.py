"""Tests for Qdrant boot polling and health self-healing.

Covers:
- Boot with Qdrant unreachable then available: API becomes ready
- Boot with Qdrant never available: gives up after timeout, reports degraded
- Health endpoint self-heals when Qdrant comes back
- Re-check rate limit prevents hammering Qdrant
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import custos.api as api_module
from custos.boot import wait_for_qdrant


class TestWaitForQdrant:
    """Unit tests for wait_for_qdrant polling logic."""

    def test_becomes_ready_after_initial_failures(self) -> None:
        """Qdrant unreachable for first few attempts, then available."""
        store = MagicMock()
        call_count = 0

        def count_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("refused")
            return 42

        store.count.side_effect = count_side_effect

        with patch("custos.boot.time.sleep"):
            result = wait_for_qdrant(store, timeout=10.0, interval=0.01)

        assert result is True
        assert call_count == 3

    def test_gives_up_after_timeout(self) -> None:
        """Qdrant never available: returns False without hanging."""
        store = MagicMock()
        store.count.side_effect = ConnectionError("refused")

        # Use a very short timeout so test is fast
        start = time.monotonic()
        with patch("custos.boot.time.sleep"):
            # With interval > timeout remaining, it exits immediately
            result = wait_for_qdrant(store, timeout=0.05, interval=0.1)
        elapsed = time.monotonic() - start

        assert result is False
        assert elapsed < 2.0  # Should not hang


class TestHealthSelfHeal:
    """Tests for the /api/health self-healing behavior."""

    def setup_method(self) -> None:
        """Save original state."""
        self._orig_ready = api_module._index_ready
        self._orig_chunks = api_module._index_chunks
        self._orig_expected = api_module._index_expected
        self._orig_recheck = api_module._last_recheck

    def teardown_method(self) -> None:
        """Restore original state."""
        api_module._index_ready = self._orig_ready
        api_module._index_chunks = self._orig_chunks
        api_module._index_expected = self._orig_expected
        api_module._last_recheck = self._orig_recheck

    def test_self_heals_when_qdrant_returns(self) -> None:
        """Health flips to ok when Qdrant becomes reachable again."""
        api_module._index_ready = False
        api_module._last_recheck = 0.0  # Allow immediate re-check

        with patch("custos.api.ensure_index_ready", return_value=(50, 50)):
            client = TestClient(api_module.app)
            response = client.get("/api/health")

        assert response.json() == {"status": "ok"}
        assert api_module._index_ready is True

    def test_stays_degraded_when_qdrant_still_down(self) -> None:
        """Health stays degraded if Qdrant is still unreachable."""
        api_module._index_ready = False
        api_module._last_recheck = 0.0

        with patch("custos.api.ensure_index_ready", side_effect=ConnectionError("refused")):
            client = TestClient(api_module.app)
            response = client.get("/api/health")

        assert response.json() == {"status": "degraded"}
        assert api_module._index_ready is False

    def test_recheck_rate_limited(self) -> None:
        """Repeated health calls do not trigger repeated re-checks."""
        api_module._index_ready = False
        # Set last recheck to "just now" so rate limit blocks
        api_module._last_recheck = time.monotonic()

        mock_ensure = MagicMock(return_value=(50, 50))
        with patch("custos.api.ensure_index_ready", mock_ensure):
            client = TestClient(api_module.app)
            # Call health 5 times rapidly
            for _ in range(5):
                response = client.get("/api/health")
                assert response.json() == {"status": "degraded"}

        # ensure_index_ready should never have been called (rate limited)
        mock_ensure.assert_not_called()

    def test_recheck_allowed_after_interval(self) -> None:
        """Re-check fires again after the interval elapses."""
        api_module._index_ready = False
        # Set last recheck far enough in the past
        api_module._last_recheck = time.monotonic() - api_module.HEALTH_RECHECK_INTERVAL - 1

        mock_ensure = MagicMock(return_value=(50, 50))
        with patch("custos.api.ensure_index_ready", mock_ensure):
            client = TestClient(api_module.app)
            response = client.get("/api/health")

        assert response.json() == {"status": "ok"}
        mock_ensure.assert_called_once()
