"""Tests for PendingActionStore.

Covers creation, session binding, TTL expiration, one-shot consumption,
and cleanup. These are security invariants, not just functional tests.
"""

from __future__ import annotations

import time

from custos.pending_actions import PendingAction, PendingActionStore


class TestPendingActionCreation:
    """Creating a pending action produces a valid, retrievable entry."""

    def test_create_returns_action_with_uuid(self) -> None:
        store = PendingActionStore()
        action = store.create("session-1", "send_email", {"to": "a@b.com"})
        assert action.action_id
        assert len(action.action_id) == 36  # uuid4 format

    def test_create_stores_session_and_tool(self) -> None:
        store = PendingActionStore()
        action = store.create("session-1", "send_email", {"to": "a@b.com"})
        assert action.session_id == "session-1"
        assert action.tool_name == "send_email"
        assert action.arguments == {"to": "a@b.com"}

    def test_get_returns_created_action(self) -> None:
        store = PendingActionStore()
        action = store.create("s1", "send_email", {})
        retrieved = store.get(action.action_id)
        assert retrieved is not None
        assert retrieved.action_id == action.action_id

    def test_get_unknown_returns_none(self) -> None:
        store = PendingActionStore()
        assert store.get("nonexistent-id") is None


class TestPendingActionConsumption:
    """Actions are one-shot: consume removes them from the store."""

    def test_consume_returns_and_removes(self) -> None:
        store = PendingActionStore()
        action = store.create("s1", "send_email", {})
        consumed = store.consume(action.action_id)
        assert consumed is not None
        assert consumed.action_id == action.action_id
        assert store.get(action.action_id) is None

    def test_consume_unknown_returns_none(self) -> None:
        store = PendingActionStore()
        assert store.consume("nonexistent") is None

    def test_double_consume_returns_none(self) -> None:
        store = PendingActionStore()
        action = store.create("s1", "send_email", {})
        store.consume(action.action_id)
        assert store.consume(action.action_id) is None


class TestPendingActionExpiry:
    """Expired actions cannot be confirmed."""

    def test_not_expired_when_fresh(self) -> None:
        action = PendingAction(
            action_id="test",
            session_id="s1",
            tool_name="send_email",
            arguments={},
        )
        assert not action.expired

    def test_expired_after_ttl(self) -> None:
        action = PendingAction(
            action_id="test",
            session_id="s1",
            tool_name="send_email",
            arguments={},
            created_at=time.monotonic() - 400,
            ttl_seconds=300,
        )
        assert action.expired

    def test_cleanup_removes_expired(self) -> None:
        store = PendingActionStore()
        # Create an expired action by patching created_at
        action = store.create("s1", "send_email", {})
        action.created_at = time.monotonic() - 400
        # Create a fresh action
        fresh = store.create("s1", "file_ticket", {})

        removed = store.cleanup_expired()
        assert removed == 1
        assert store.get(action.action_id) is None
        assert store.get(fresh.action_id) is not None


class TestPendingActionSessionBinding:
    """Session ID must match for confirmation."""

    def test_different_sessions_get_different_actions(self) -> None:
        store = PendingActionStore()
        a1 = store.create("session-1", "send_email", {})
        a2 = store.create("session-2", "send_email", {})
        assert a1.session_id != a2.session_id
        assert a1.action_id != a2.action_id
