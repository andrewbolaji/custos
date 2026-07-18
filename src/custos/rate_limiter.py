"""Rate limiting and cost tracking for production deployment.

Two-tier cap (daily + monthly) persisted to a JSON file on a named
volume so counters survive container restarts. Per-IP rate limiting
and per-session quotas are in-memory (acceptable to lose on restart;
they are abuse controls, not budget controls).

All limits are configurable via environment variables with sensible
defaults. Andrew edits ~/.env and restarts the API in thirty seconds.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (all from environment, with defaults)
# ---------------------------------------------------------------------------

DAILY_CAP = int(os.environ.get("CUSTOS_DAILY_CAP", "150"))
MONTHLY_CAP = int(os.environ.get("CUSTOS_MONTHLY_CAP", "4000"))
SESSION_QUOTA = int(os.environ.get("CUSTOS_SESSION_QUOTA", "20"))
RATE_PER_MIN = int(os.environ.get("CUSTOS_RATE_PER_MIN", "8"))
MAX_QUERY_LEN = int(os.environ.get("CUSTOS_MAX_QUERY_LEN", "500"))

# Per-query cost estimate (Sonnet: $3/MTok input, $15/MTok output)
EST_INPUT_TOKENS = 4050
EST_OUTPUT_TOKENS = 600
EST_COST_PER_QUERY = (
    EST_INPUT_TOKENS / 1_000_000 * 3.0
    + EST_OUTPUT_TOKENS / 1_000_000 * 15.0
)

# Persistence path (inside the app_data volume in production)
DATA_DIR = Path(os.environ.get("CUSTOS_DATA_DIR", "data"))
COUNTERS_FILE = DATA_DIR / "counters.json"


@dataclass
class _IPBucket:
    """Per-IP sliding window rate limiter."""

    timestamps: list[float] = field(default_factory=list)

    def allow(self, now: float, limit: int, window: float = 60.0) -> bool:
        """Return True if the request is allowed."""
        cutoff = now - window
        self.timestamps = [t for t in self.timestamps if t > cutoff]
        if len(self.timestamps) >= limit:
            return False
        self.timestamps.append(now)
        return True


class RateLimiter:
    """Production rate limiter with persisted two-tier caps.

    Thread-safe. The daily and monthly counters persist to a JSON file
    so they survive container restarts. Per-IP and per-session counters
    are in-memory.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._ip_buckets: dict[str, _IPBucket] = {}
        self._session_counts: dict[str, int] = {}

        # Persisted counters
        self._today: str = ""
        self._month: str = ""
        self._requests_today: int = 0
        self._requests_month: int = 0
        self._cost_today: float = 0.0
        self._cost_month: float = 0.0

        self._load()

    def _load(self) -> None:
        """Load persisted counters from disk."""
        if not COUNTERS_FILE.exists():
            self._reset_today()
            self._reset_month()
            return

        try:
            data = json.loads(COUNTERS_FILE.read_text())
            today = _today_str()
            month = _month_str()

            if data.get("date") == today:
                self._today = today
                self._requests_today = data.get("requests_today", 0)
                self._cost_today = data.get("cost_today", 0.0)
            else:
                self._reset_today()

            if data.get("month") == month:
                self._month = month
                self._requests_month = data.get("requests_month", 0)
                self._cost_month = data.get("cost_month", 0.0)
            else:
                self._reset_month()
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load counters; resetting")
            self._reset_today()
            self._reset_month()

    def _reset_today(self) -> None:
        self._today = _today_str()
        self._requests_today = 0
        self._cost_today = 0.0

    def _reset_month(self) -> None:
        self._month = _month_str()
        self._requests_month = 0
        self._cost_month = 0.0

    def _persist(self) -> None:
        """Write counters to disk."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            COUNTERS_FILE.write_text(json.dumps({
                "date": self._today,
                "month": self._month,
                "requests_today": self._requests_today,
                "requests_month": self._requests_month,
                "cost_today": self._cost_today,
                "cost_month": self._cost_month,
            }))
        except OSError:
            logger.warning("Failed to persist counters")

    def check_request(
        self,
        client_ip: str,
        session_id: str,
        query_length: int,
    ) -> str | None:
        """Check all limits. Returns None if allowed, or an error message."""
        if query_length > MAX_QUERY_LEN:
            return (
                f"Your question is too long ({query_length} characters). "
                f"Please keep it under {MAX_QUERY_LEN} characters."
            )

        with self._lock:
            # Roll over date/month if needed
            today = _today_str()
            if self._today != today:
                self._reset_today()
            month = _month_str()
            if self._month != month:
                self._reset_month()

            # Monthly cap (the real budget control)
            if self._requests_month >= MONTHLY_CAP:
                return (
                    "This demo has reached its monthly usage limit. "
                    "It resets on the 1st. "
                    "For a walkthrough or extended access, contact Andrew."
                )

            # Daily cap (spike protection)
            if self._requests_today >= DAILY_CAP:
                return (
                    "This demo has reached its daily usage limit. "
                    "It resets at midnight UTC. "
                    "For a walkthrough or extended access, contact Andrew."
                )

            # Per-IP rate limit
            now = time.monotonic()
            bucket = self._ip_buckets.setdefault(client_ip, _IPBucket())
            if not bucket.allow(now, RATE_PER_MIN):
                return "You are sending requests too quickly. Please slow down."

            # Per-session quota
            count = self._session_counts.get(session_id, 0)
            if count >= SESSION_QUOTA:
                return (
                    f"You have used all {SESSION_QUOTA} questions in this session. "
                    "Reload the page to start a new session."
                )

            return None

    def record_api_call(self) -> None:
        """Record a billed API call (one per model invocation).

        Called from the LLM client's on_api_call callback, which fires
        on every messages.create or messages.stream call -- including
        every step of a multi-step agent run. This is the single point
        where cost is counted, making it structurally impossible to
        add a code path that spends money without counting it.
        """
        with self._lock:
            today = _today_str()
            if self._today != today:
                self._reset_today()
            month = _month_str()
            if self._month != month:
                self._reset_month()

            self._requests_today += 1
            self._requests_month += 1
            self._cost_today += EST_COST_PER_QUERY
            self._cost_month += EST_COST_PER_QUERY
            self._persist()

    def record_session_query(self, session_id: str) -> None:
        """Record a query against the per-session quota.

        Called once per user request (not per agent step), at the
        endpoint level before the model is called.
        """
        with self._lock:
            self._session_counts[session_id] = (
                self._session_counts.get(session_id, 0) + 1
            )

    def get_status(self) -> dict[str, object]:
        """Return current counters for the admin endpoint."""
        with self._lock:
            today = _today_str()
            if self._today != today:
                self._reset_today()
            month = _month_str()
            if self._month != month:
                self._reset_month()

            return {
                "requests_today": self._requests_today,
                "daily_cap": DAILY_CAP,
                "requests_month": self._requests_month,
                "monthly_cap": MONTHLY_CAP,
                "estimated_cost_today": f"${self._cost_today:.2f}",
                "estimated_cost_month": f"${self._cost_month:.2f}",
                "pct_monthly_used": round(
                    self._requests_month / MONTHLY_CAP * 100, 1
                ) if MONTHLY_CAP > 0 else 0,
                "note": (
                    "Cost is estimated from token counts and published pricing. "
                    "Actual billed amount may differ."
                ),
            }

    def cleanup_stale_ips(self) -> None:
        """Remove IP buckets with no recent activity."""
        with self._lock:
            now = time.monotonic()
            stale = [
                ip for ip, bucket in self._ip_buckets.items()
                if not bucket.timestamps or bucket.timestamps[-1] < now - 300
            ]
            for ip in stale:
                del self._ip_buckets[ip]


def _today_str() -> str:
    return date.today().isoformat()


def _month_str() -> str:
    return date.today().strftime("%Y-%m")
