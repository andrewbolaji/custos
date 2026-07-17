"""In-memory store for pending side-effectful actions.

When the agent loop encounters a side-effectful tool call, it creates a
PendingAction instead of executing. The action is stored here with an
unguessable UUID, bound to the user's session_id, and expires after a TTL.

The /api/chat/confirm endpoint looks up the action by ID, validates the
session match, and either executes (simulated) or rejects.

SECURITY INVARIANTS:
- Action IDs are uuid4 (unguessable). A user cannot enumerate or guess
  another session's pending actions.
- Session binding: only the session that created the action can confirm it.
- TTL: expired actions cannot be confirmed (prevents stale approvals).
- Each action can only be confirmed/rejected once (consumed on use).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

DEFAULT_TTL_SECONDS = 300  # 5 minutes


@dataclass
class PendingAction:
    """A side-effectful tool call awaiting user confirmation."""

    action_id: str
    session_id: str
    tool_name: str
    arguments: dict[str, Any]
    created_at: float = field(default_factory=time.monotonic)
    ttl_seconds: float = DEFAULT_TTL_SECONDS

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self.created_at) >= self.ttl_seconds


class PendingActionStore:
    """Thread-safe in-memory store for pending actions.

    In production this would be Redis or similar. For the demo, an
    in-memory dict is sufficient since we run a single process.
    """

    def __init__(self) -> None:
        self._actions: dict[str, PendingAction] = {}

    def create(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> PendingAction:
        """Create a new pending action and return it."""
        action_id = str(uuid.uuid4())
        action = PendingAction(
            action_id=action_id,
            session_id=session_id,
            tool_name=tool_name,
            arguments=arguments,
        )
        self._actions[action_id] = action
        return action

    def get(self, action_id: str) -> PendingAction | None:
        """Look up a pending action by ID. Returns None if not found."""
        return self._actions.get(action_id)

    def consume(self, action_id: str) -> PendingAction | None:
        """Remove and return a pending action. Returns None if not found."""
        return self._actions.pop(action_id, None)

    def cleanup_expired(self) -> int:
        """Remove all expired actions. Returns the count removed."""
        expired_ids = [
            aid for aid, action in self._actions.items() if action.expired
        ]
        for aid in expired_ids:
            del self._actions[aid]
        return len(expired_ids)

    @property
    def count(self) -> int:
        return len(self._actions)
