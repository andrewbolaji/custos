"""Tests for vector store boot polling and health self-healing.

wait_for_qdrant/ensure_index_ready work against any VectorStore backend
(Qdrant or pgvector, selected by CUSTOS_VECTOR_BACKEND) -- these tests use a
mocked store, so they exercise the polling/self-heal logic itself, not a
specific backend. Names are historical (Qdrant was the only backend when
they were written).

Covers:
- Boot with the store unreachable then available: API becomes ready
- Boot with the store never available: gives up after timeout, reports degraded
- Health endpoint self-heals when the store comes back
- Re-check rate limit prevents hammering the store
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import custos.api as api_module
from custos.boot import wait_for_qdrant


class TestWaitForQdrant:
    """Unit tests for wait_for_qdrant polling logic."""

    def test_becomes_ready_after_initial_failures(self) -> None:
        """Qdrant unreachable for first few attempts, then available.

        Mocks ping(), not count(): count() swallows every exception and
        returns 0 on failure (see vector_store.py), so it can never raise
        here -- ping() is the method wait_for_qdrant actually polls with,
        specifically because it does raise.
        """
        store = MagicMock()
        call_count = 0

        def ping_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("refused")
            return None

        store.ping.side_effect = ping_side_effect

        with patch("custos.boot.time.sleep"):
            result = wait_for_qdrant(store, timeout=10.0, interval=0.01)

        assert result is True
        assert call_count == 3

    def test_gives_up_after_timeout(self) -> None:
        """Qdrant never available: returns False without hanging."""
        store = MagicMock()
        store.ping.side_effect = ConnectionError("refused")

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

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert api_module._index_ready is True

    def test_stays_degraded_when_qdrant_still_down(self) -> None:
        """Health stays degraded if Qdrant is still unreachable."""
        api_module._index_ready = False
        api_module._last_recheck = 0.0

        with patch("custos.api.ensure_index_ready", side_effect=ConnectionError("refused")):
            client = TestClient(api_module.app)
            response = client.get("/api/health")

        assert response.status_code == 503
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
                assert response.status_code == 503
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

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        mock_ensure.assert_called_once()

    def test_self_heal_lock_prevents_concurrent_reindex(self) -> None:
        """Concurrent /api/health probes (the ALB has one health-checker per
        subnet, see alb.tf/network.tf) must not both trigger a reindex.
        Only the probe that wins the non-blocking lock acquisition should
        call ensure_index_ready; the rest must return immediately via the
        skip path without ever calling it.

        Uses events instead of a sleep-based race so this is deterministic:
        the "winning" probe is held inside ensure_index_ready on purpose
        until the three "losing" probes have already returned, so there is
        no window where this could pass by timing luck. _get_store and
        _get_embedder are mocked so no real embedder/vector-store
        construction (slow, and not what this test is about) runs.
        """
        api_module._index_ready = False
        api_module._last_recheck = 0.0

        reindex_started = threading.Event()
        release_reindex = threading.Event()
        call_count = 0
        count_lock = threading.Lock()
        winner_release_timed_out = False

        def blocking_ensure_index_ready(embedder: object, store: object) -> tuple[int, int]:
            # Not `assert` here: this runs inside health()'s
            # `except Exception: logger.debug(...)`, which would silently
            # swallow an AssertionError and leave a confusing failure
            # somewhere downstream instead. Record it and assert after the
            # `with` block, where it will actually surface.
            nonlocal call_count, winner_release_timed_out
            with count_lock:
                call_count += 1
            reindex_started.set()
            if not release_reindex.wait(timeout=5):
                winner_release_timed_out = True
            return (50, 50)

        responses: list[int] = []
        responses_lock = threading.Lock()

        def call_health() -> None:
            client = TestClient(api_module.app)
            response = client.get("/api/health")
            with responses_lock:
                responses.append(response.status_code)

        with (
            patch("custos.api.ensure_index_ready", side_effect=blocking_ensure_index_ready),
            patch.object(api_module, "_get_store", return_value=MagicMock()),
            patch.object(api_module, "_get_embedder", return_value=MagicMock()),
        ):
            winner = threading.Thread(target=call_health)
            winner.start()
            assert reindex_started.wait(timeout=5), (
                "winning probe never entered ensure_index_ready"
            )

            # The winner now holds _self_heal_lock and is blocked inside
            # ensure_index_ready. These three land while it's still held.
            losers = [threading.Thread(target=call_health) for _ in range(3)]
            for t in losers:
                t.start()
            for t in losers:
                t.join(timeout=5)

            assert len(responses) == 3, "all three losing probes must have returned by now"

            release_reindex.set()
            winner.join(timeout=5)
            assert not winner.is_alive(), (
                "winner thread did not finish -- it may still mutate module "
                "globals after this test's teardown runs"
            )

        assert not winner_release_timed_out, "test held the winner open too long"
        assert call_count == 1, "exactly one probe should have called ensure_index_ready"
        assert not api_module._self_heal_lock.locked(), "lock must be released after use"
        assert len(responses) == 4
        # The three losing probes returned via the skip path while the lock
        # was held, so the index still looked degraded to them: 503. The
        # winning probe's own response reflects the reindex IT just
        # completed (50/50 chunks -> ready), so it alone sees 200.
        assert responses.count(503) == 3
        assert responses.count(200) == 1
