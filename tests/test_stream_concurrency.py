"""Regression test for concurrent /api/chat/stream requests.

The provider stream is synchronous and blocking, so the async API bridge must
advance it in a worker thread. Answer text is now held until complete-response
redaction, but internal stream_progress events still return control after each
provider chunk. Those checkpoints preserve disconnect checks and prevent two
requests from serializing on the event-loop thread.

The fake stream uses time.sleep to reproduce a blocking network read. Two
20-chunk requests at 0.02 seconds per chunk should finish near one request's
0.4-second duration, not the roughly 0.8 seconds expected if serialized.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pytest
from sse_starlette.sse import AppStatus

import custos.api as api_module
from custos.api import app
from custos.interfaces import Chunk
from custos.tool_registry import ToolRegistry

_TOKENS = ["0123456789ABCDE" for _ in range(20)]
_DELAY_SECONDS = 0.02  # per-token simulated blocking network read


@dataclass
class _FakeDelta:
    text: str


@dataclass
class _FakeContentBlock:
    type: str = "text"


@dataclass
class _FakeStreamEvent:
    type: str
    delta: _FakeDelta | None = None
    content_block: _FakeContentBlock | None = None


@dataclass
class _FakeFinalBlock:
    type: str = "text"
    text: str = ""


@dataclass
class _FakeFinalMessage:
    content: list[Any]


class _BlockingFakeStream:
    """Mimics anthropic's `with client.messages.stream(...) as stream:`.

    Sleeps with `time.sleep` (a REAL blocking call) before each token, the
    same way a real blocking socket read would block whatever thread is
    driving this generator. If the event loop itself is driving it directly
    (the bug), the whole process stalls for `_DELAY_SECONDS` per token.
    """

    def __init__(self, tokens: list[str], delay: float) -> None:
        self._tokens = tokens
        self._delay = delay

    def __enter__(self) -> _BlockingFakeStream:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def __iter__(self) -> Any:
        for token in self._tokens:
            time.sleep(self._delay)
            yield _FakeStreamEvent(
                type="content_block_delta", delta=_FakeDelta(text=token)
            )

    def get_final_message(self) -> _FakeFinalMessage:
        return _FakeFinalMessage(
            content=[_FakeFinalBlock(text="".join(self._tokens))]
        )


class _FakeMessages:
    def __init__(self, tokens: list[str], delay: float) -> None:
        self._tokens = tokens
        self._delay = delay

    def stream(self, **kwargs: Any) -> _BlockingFakeStream:
        return _BlockingFakeStream(self._tokens, self._delay)


class _FakeClient:
    def __init__(self, tokens: list[str], delay: float) -> None:
        self.messages = _FakeMessages(tokens, delay)


class _FakeLLM:
    """Duck-types the subset of ClaudeLLM that AgentLoop.run_streaming uses."""

    def __init__(self, tokens: list[str], delay: float) -> None:
        self.model = "fake-model"
        self.max_tokens = 1024
        self.temperature = 0.1
        self.client = _FakeClient(tokens, delay)

    def notify_api_call(self) -> None:
        pass


def _fake_chunks(query: str, user_permissions: list[str]) -> list[Chunk]:
    return [
        Chunk(
            chunk_id="c1_test",
            doc_id="doc-1",
            text="Relevant excerpt text.",
            section_path=["Section"],
            char_start=0,
            char_end=10,
            permissions=["general"],
        )
    ]


def _fake_registry(user_permissions: list[str]) -> ToolRegistry:
    # Empty on purpose: the fake stream never emits a tool_use block, so
    # no tool needs to be resolvable. This also avoids constructing the
    # real retriever (embedder + vector store), which this test must not
    # touch (see module docstring: no real LLM/embedder/vector store).
    return ToolRegistry()


async def _drive_stream_request(
    session_id: str, timestamps: list[float], t0: float
) -> None:
    """Call the ASGI app directly and record a wall-clock timestamp
    (relative to t0) for every non-empty response body chunk, in real time
    as `send()` receives it -- see module docstring for why this does not
    go through httpx.ASGITransport.
    """
    body = json.dumps({
        "query": "What is the PTO policy?",
        "user_permissions": ["general"],
        "session_id": session_id,
    }).encode()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/api/chat/stream",
        "raw_path": b"/api/chat/stream",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "server": ("testserver", 80),
        # A distinct client identity from Starlette's TestClient default
        # ("testclient"). _rate_limiter is a module-level singleton shared
        # by the whole test session and keys its per-IP bucket off this;
        # sharing "testclient" with the many other tests that use
        # TestClient(app) elsewhere in the suite would make this test's
        # pass/fail depend on test execution order.
        "client": ("stream-concurrency-test-client", 12345),
        "scheme": "http",
    }

    body_sent = False

    async def receive() -> dict[str, Any]:
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        # Simulate a connection that stays open for the rest of the test.
        # Starlette's Request.is_disconnected() peeks at this receive
        # channel through an already-cancelled anyio.CancelScope; hitting
        # a real checkpoint here (instead of returning immediately) is
        # what makes that peek resolve as "nothing pending yet" rather
        # than reporting a disconnect.
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}  # pragma: no cover -- unreachable

    status_code: int | None = None

    async def send(message: dict[str, Any]) -> None:
        nonlocal status_code
        if message["type"] == "http.response.start":
            status_code = message["status"]
        elif message["type"] == "http.response.body" and message.get("body"):
            timestamps.append(time.monotonic() - t0)

    await app(scope, receive, send)
    assert status_code == 200, f"session {session_id!r} got status {status_code}"


async def _fire_two_concurrent_requests() -> tuple[list[float], list[float], float]:
    timestamps_a: list[float] = []
    timestamps_b: list[float] = []
    t0 = time.monotonic()
    await asyncio.gather(
        _drive_stream_request("session-a", timestamps_a, t0),
        _drive_stream_request("session-b", timestamps_b, t0),
    )
    total_wall_clock = time.monotonic() - t0
    return timestamps_a, timestamps_b, total_wall_clock


@pytest.mark.skipif(
    os.environ.get("CUSTOS_VECTOR_BACKEND", "qdrant") != "qdrant"
    or os.environ.get("CUSTOS_AGENT_RUNTIME", "native") != "native",
    reason=(
        "This test exercises only chat_stream's SSE bridging (event-loop "
        "concurrency), with _get_llm, _retrieve_permitted_chunks, and "
        "_build_registry all mocked out. It never constructs a real "
        "retriever, embedder, or vector store and never selects an agent "
        "runtime, so CUSTOS_VECTOR_BACKEND / CUSTOS_AGENT_RUNTIME cannot "
        "change its outcome. Running it on all 3 CI matrix legs would "
        "repeat an identical, timing-sensitive test 3x for no additional "
        "coverage and 3x the flake surface -- it runs once, on the "
        "qdrant/native leg (also the default when running locally without "
        "either env var set)."
    ),
)
def test_two_concurrent_streams_interleave() -> None:
    """Two concurrent streaming requests must make genuine concurrent
    progress, not take turns on one blocked thread.

    Fails against the pre-fix code: see the module docstring for the
    total wall-clock evidence and why a blocking fake stream discriminates
    serialized from concurrent execution.
    """
    # sse_starlette's AppStatus.should_exit_event is a process-global
    # anyio.Event, lazily bound to whichever event loop first triggers
    # EventSourceResponse's shutdown listener. Other tests in the suite
    # (e.g. test_api.py::test_stream_retrieval_failure_emits_notice) also
    # enter the real SSE path via Starlette's TestClient, which binds this
    # to ITS OWN portal event loop; by the time this test runs, that loop
    # may already be torn down, and reusing the stale-bound event raises
    # "bound to a different event loop" (see tests/test_stream.py's module
    # docstring for the same gotcha). Reset before AND after this test's
    # own asyncio.run() so it is lazily recreated against whichever loop
    # is actually current, both for this test and for whatever runs next.
    AppStatus.should_exit_event = None
    AppStatus.should_exit = False
    with (
        patch.object(api_module, "_index_ready", True),
        patch.object(api_module, "_get_llm", return_value=_FakeLLM(_TOKENS, _DELAY_SECONDS)),
        patch.object(api_module, "_retrieve_permitted_chunks", side_effect=_fake_chunks),
        patch.object(api_module, "_build_registry", side_effect=_fake_registry),
    ):
        try:
            timestamps_a, timestamps_b, total_wall_clock = asyncio.run(
                _fire_two_concurrent_requests()
            )
        finally:
            AppStatus.should_exit_event = None
            AppStatus.should_exit = False

    # Each response still emits status, answer, and done SSE frames. Internal
    # progress events are deliberately not exposed to the client.
    assert len(timestamps_a) >= 3, f"Request A got too few chunks: {timestamps_a}"
    assert len(timestamps_b) >= 3, f"Request B got too few chunks: {timestamps_b}"

    expected_solo_duration = len(_TOKENS) * _DELAY_SECONDS
    assert total_wall_clock < expected_solo_duration * 1.5, (
        f"total_wall_clock={total_wall_clock:.3f}s is not close to a "
        f"single request's own duration (~{expected_solo_duration:.3f}s); "
        f"it looks like the two requests ran serially instead of "
        f"concurrently."
    )
