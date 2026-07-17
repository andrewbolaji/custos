"""Tests for POST /api/chat/confirm.

Covers: approve, reject, session mismatch, expired, not found, double
confirm. These are security tests -- the confirm endpoint is a new
access-control surface.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from custos.api import _pending_actions, app

client = TestClient(app)


def _seed_action(
    session_id: str = "test-session",
    tool_name: str = "send_email",
    arguments: dict | None = None,
) -> str:
    """Seed a pending action and return its ID."""
    action = _pending_actions.create(
        session_id=session_id,
        tool_name=tool_name,
        arguments=arguments or {"to": "a@example.com", "subject": "Hi", "body": "Hello"},
    )
    return action.action_id


class TestConfirmEndpointApprove:
    """Approving a valid action executes the (simulated) tool."""

    def test_approve_returns_executed(self) -> None:
        action_id = _seed_action()
        resp = client.post("/api/chat/confirm", json={
            "action_id": action_id,
            "session_id": "test-session",
            "approved": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "executed"
        assert data["tool_name"] == "send_email"
        assert data["simulated"] is True
        assert "(simulated)" in data["output"]

    def test_approve_file_ticket(self) -> None:
        action_id = _seed_action(
            tool_name="file_ticket",
            arguments={"title": "Fix leak", "description": "Kitchen sink"},
        )
        resp = client.post("/api/chat/confirm", json={
            "action_id": action_id,
            "session_id": "test-session",
            "approved": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "executed"
        assert data["simulated"] is True


class TestConfirmEndpointReject:
    """Rejecting an action returns rejected status without execution."""

    def test_reject_returns_rejected(self) -> None:
        action_id = _seed_action()
        resp = client.post("/api/chat/confirm", json={
            "action_id": action_id,
            "session_id": "test-session",
            "approved": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rejected"


class TestConfirmEndpointSecurity:
    """Session mismatch, expiry, not found, and double confirm."""

    def test_session_mismatch_returns_403(self) -> None:
        action_id = _seed_action(session_id="session-A")
        resp = client.post("/api/chat/confirm", json={
            "action_id": action_id,
            "session_id": "session-B",
            "approved": True,
        })
        assert resp.status_code == 403

    def test_not_found_returns_404(self) -> None:
        resp = client.post("/api/chat/confirm", json={
            "action_id": "nonexistent-uuid",
            "session_id": "test-session",
            "approved": True,
        })
        assert resp.status_code == 404

    def test_double_confirm_returns_404(self) -> None:
        action_id = _seed_action()
        client.post("/api/chat/confirm", json={
            "action_id": action_id,
            "session_id": "test-session",
            "approved": True,
        })
        resp = client.post("/api/chat/confirm", json={
            "action_id": action_id,
            "session_id": "test-session",
            "approved": True,
        })
        assert resp.status_code == 404

    def test_expired_returns_410(self) -> None:
        action_id = _seed_action()
        action = _pending_actions.get(action_id)
        assert action is not None
        action.created_at = time.monotonic() - 400
        resp = client.post("/api/chat/confirm", json={
            "action_id": action_id,
            "session_id": "test-session",
            "approved": True,
        })
        assert resp.status_code == 410

    def test_missing_fields_returns_422(self) -> None:
        resp = client.post("/api/chat/confirm", json={})
        assert resp.status_code == 422
