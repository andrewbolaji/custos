"""Tests for the rate limiter and cost tracker."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from custos.rate_limiter import RateLimiter


class TestRateLimiter:
    def _make_limiter(self, tmp: Path, **env_overrides: str) -> RateLimiter:
        """Create a rate limiter with a temp data dir."""
        defaults = {
            "CUSTOS_DATA_DIR": str(tmp),
            "CUSTOS_DAILY_CAP": "5",
            "CUSTOS_MONTHLY_CAP": "20",
            "CUSTOS_SESSION_QUOTA": "3",
            "CUSTOS_RATE_PER_MIN": "2",
            "CUSTOS_MAX_QUERY_LEN": "100",
        }
        defaults.update(env_overrides)
        with patch.dict("os.environ", defaults):
            # Re-import to pick up env vars
            import importlib

            import custos.rate_limiter as mod

            importlib.reload(mod)
            return mod.RateLimiter()

    def test_allows_normal_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rl = self._make_limiter(Path(tmp))
            result = rl.check_request("1.2.3.4", "sess1", 50)
            assert result is None

    def test_blocks_long_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rl = self._make_limiter(Path(tmp))
            result = rl.check_request("1.2.3.4", "sess1", 200)
            assert result is not None
            assert "too long" in result

    def test_blocks_after_daily_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # High per-IP rate and session quota so they don't interfere
            rl = self._make_limiter(
                Path(tmp), CUSTOS_RATE_PER_MIN="100", CUSTOS_SESSION_QUOTA="100"
            )
            for i in range(5):
                assert rl.check_request("1.2.3.4", f"sess{i}", 10) is None
                rl.record_api_call()
            result = rl.check_request("1.2.3.4", "sess99", 10)
            assert result is not None
            assert "daily" in result.lower()

    def test_blocks_after_session_quota(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # High per-IP rate so it doesn't interfere
            rl = self._make_limiter(Path(tmp), CUSTOS_RATE_PER_MIN="100")
            for _ in range(3):
                assert rl.check_request("1.2.3.4", "sess1", 10) is None
                rl.record_session_query("sess1")
            result = rl.check_request("1.2.3.4", "sess1", 10)
            assert result is not None
            assert "session" in result.lower()

    def test_per_ip_rate_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rl = self._make_limiter(Path(tmp))
            # Send 2 requests quickly (limit is 2/min)
            assert rl.check_request("1.2.3.4", "sess1", 10) is None
            assert rl.check_request("1.2.3.4", "sess2", 10) is None
            # Third should be blocked
            result = rl.check_request("1.2.3.4", "sess3", 10)
            assert result is not None
            assert "too quickly" in result.lower()

    def test_different_ips_independent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rl = self._make_limiter(Path(tmp))
            assert rl.check_request("1.2.3.4", "s1", 10) is None
            assert rl.check_request("1.2.3.4", "s2", 10) is None
            # Different IP is not affected
            assert rl.check_request("5.6.7.8", "s3", 10) is None

    def test_counters_persist_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rl = self._make_limiter(Path(tmp))
            rl.record_api_call()
            rl.record_api_call()

            # Read the file directly
            counters = json.loads(
                (Path(tmp) / "counters.json").read_text()
            )
            assert counters["requests_today"] == 2
            assert counters["requests_month"] == 2

    def test_counters_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rl1 = self._make_limiter(Path(tmp))
            for _ in range(3):
                rl1.record_api_call()

            # Create a new limiter (simulating restart)
            rl2 = self._make_limiter(Path(tmp))
            status = rl2.get_status()
            assert status["requests_today"] == 3
            assert status["requests_month"] == 3

    def test_get_status_includes_all_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rl = self._make_limiter(Path(tmp))
            status = rl.get_status()
            assert "requests_today" in status
            assert "daily_cap" in status
            assert "requests_month" in status
            assert "monthly_cap" in status
            assert "estimated_cost_today" in status
            assert "estimated_cost_month" in status
            assert "pct_monthly_used" in status
            assert "note" in status


class TestApiCallCounting:
    """Regression tests for cost-control holes."""

    def test_multi_step_agent_counts_each_step(self) -> None:
        """A multi-step agent run must increment the counter once per
        model call, not once per HTTP request. Verified: removing
        notify_api_call from the agent loop would cause this to fail
        (counter stays at 0).
        """
        from unittest.mock import MagicMock

        call_count = 0

        def on_call() -> None:
            nonlocal call_count
            call_count += 1

        from custos.llm import ClaudeLLM

        llm = ClaudeLLM.__new__(ClaudeLLM)
        llm._model = "test"
        llm._max_tokens = 1024
        llm._temperature = 0.1
        llm._client = MagicMock()
        llm._on_api_call = on_call

        from dataclasses import dataclass
        from typing import Any

        @dataclass
        class FakeBlock:
            type: str = "text"
            text: str = "answer"

        @dataclass
        class FakeToolBlock:
            type: str = "tool_use"
            id: str = "tu_1"
            name: str = "lookup"
            input: dict[str, Any] | None = None
            def __post_init__(self) -> None:
                if self.input is None:
                    self.input = {"q": "test"}

        @dataclass
        class FakeResponse:
            content: list[Any] | None = None
            def __post_init__(self) -> None:
                if self.content is None:
                    self.content = [FakeBlock()]

        from custos.agent_loop import AgentLoop
        from custos.interfaces import Chunk, Tool, ToolResult
        from custos.tool_registry import ToolRegistry

        class ReadTool(Tool):
            @property
            def name(self) -> str:
                return "lookup"
            @property
            def description(self) -> str:
                return "lookup"
            @property
            def side_effectful(self) -> bool:
                return False
            @property
            def input_schema(self) -> dict[str, Any]:
                return {"type": "object", "properties": {}}
            def run(self, arguments: dict[str, Any]) -> ToolResult:
                return ToolResult(tool_name="lookup", output="found")

        # Two steps: tool call then final answer
        llm._client.messages.create.side_effect = [
            FakeResponse(content=[FakeToolBlock()]),
            FakeResponse(content=[FakeBlock()]),
        ]

        registry = ToolRegistry()
        registry.register(ReadTool())
        chunk = Chunk(
            chunk_id="c_1", doc_id="d", text="text",
            section_path=["S"], char_start=0, char_end=4,
            permissions=["general"],
        )
        parts = ClaudeLLM.build_prompt("System.", [chunk])
        loop = AgentLoop(llm=llm, registry=registry)
        loop.run(parts, "test")

        # Two model calls = two on_api_call invocations
        assert call_count == 2, (
            f"Expected 2 API calls (2 steps), got {call_count}. "
            "Multi-step agent runs must count each step."
        )

    def test_eval_harness_does_not_count(self) -> None:
        """The eval harness creates ClaudeLLM without on_api_call,
        so eval runs do not pollute production counters.
        """
        from custos.llm import ClaudeLLM

        llm = ClaudeLLM.__new__(ClaudeLLM)
        llm._on_api_call = None
        # Should not raise
        llm.notify_api_call()


class TestAdminEndpoint:
    def test_admin_returns_404_without_token(self) -> None:
        from fastapi.testclient import TestClient

        from custos.api import app

        client = TestClient(app)
        response = client.get("/api/admin/status")
        assert response.status_code == 404

    def test_admin_returns_404_with_wrong_token(self) -> None:
        from fastapi.testclient import TestClient

        from custos.api import app

        client = TestClient(app)
        response = client.get(
            "/api/admin/status",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 404
