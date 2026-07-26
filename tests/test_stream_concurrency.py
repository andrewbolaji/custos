"""Regression test: two concurrent /api/chat/stream requests must be served
concurrently, not serialized behind a blocked event loop.

BUG (found during the cancel-mid-stream work, tracked and fixed here):
chat_stream's event_generator is `async def` but drove AgentLoop.run_streaming
-- a plain SYNCHRONOUS generator wrapping the Anthropic SDK's sync streaming
client -- with a bare `for event in stream_iter:`. Every blocking read inside
that generator (the Anthropic HTTP read, the embedding call, the vector store
query, tool execution, synchronous disk logging) ran directly on the asyncio
event loop thread. A second concurrent request's ASGI task could only run
during the rare checkpoints the handler happens to await (e.g.
`is_disconnected()`), so its own blocking work still competed for the same
single thread as the first request's -- both requests together took
roughly as long as the two run back to back, not as long as the slower one
alone.

This test does not touch a real LLM, embedder, or vector store. It mocks
`_get_llm`, `_retrieve_permitted_chunks`, and `_build_registry` so it
exercises exactly one thing: whether chat_stream's SSE bridging lets two
independent streams make genuine concurrent progress on a single asyncio
event loop (the same execution model `make serve` uses in production -- a
single uvicorn worker). The fake Anthropic stream sleeps between tokens
with `time.sleep` (a real blocking call, not `asyncio.sleep`) because that
is what actually reproduces the bug: an `asyncio.sleep` inside the fake
would yield control back to the loop on its own and mask a real
event-loop stall. It emits enough tokens to cross the agent loop's 64-char
streaming guard buffer many times over, so each request produces ~18
separate SSE chunks (not one lump at the end) -- enough data points to
measure each stream's own steady-state throughput, not just its total
duration.

Deliberately bypasses httpx.ASGITransport. ASGITransport's
handle_async_request awaits the ENTIRE `app(scope, receive, send)` call to
completion, collecting every response chunk into a list, before it ever
constructs a Response for its caller -- there is no way to observe
per-chunk arrival time through it (verified: a spike using it showed both
requests' first AND last chunk landing at the same instant, because the
whole SSE body arrives as one already-joined blob only after the app
finishes). So this test drives the ASGI callable directly with a minimal
hand-rolled receive/send pair, timestamping each `http.response.body` the
app sends in real time -- the same signal a real socket would give a real
HTTP client.

Why total wall-clock, not raw range-overlap, is the assertion that
actually discriminates: a spike measurement against the pre-fix code
showed request B's chunk range DOES overlap request A's even though
they're serialized -- the one `await is_disconnected()` checkpoint per
event is enough for asyncio to swap tasks back and forth, so the *chunks*
interleave in arrival order even while the *work* stays fully serialized
(one request's blocking sleep still fully occupies the sole thread while
it runs; only which request is currently occupying it alternates). What
does NOT survive that swapping is throughput: pre-fix, each stream's own
median gap between consecutive chunks comes out close to DOUBLE the
configured per-token delay, because the two requests are still taking
turns on one thread. Post-fix, each stream's own median gap matches the
configured delay almost exactly, because the other request's blocking
work runs on its own thread and no longer competes. That is what
assertion (a) below actually measures.

--- MEASURED BEFORE NUMBERS (broken code, api.py pre-fix, 3 runs) ---
Run 1: total=0.944s  median_gap_a=0.047s  median_gap_b=0.046s
Run 2: total=0.991s  median_gap_a=0.049s  median_gap_b=0.048s
Run 3: total=0.978s  median_gap_a=0.048s  median_gap_b=0.048s
Configured per-token delay: 0.02s. Each stream's own median gap is ~2.3-2.45x
the configured delay (both requests sharing one thread), and total
wall-clock (~0.94-0.99s) is close to 2x the ~0.4s a single request takes
alone -- the serialized-behind-one-request signature the bug report
predicted. (Measured by temporarily reverting src/custos/api.py to the
pre-fix version via `git stash` and re-running this same test file
unmodified.)

--- MEASURED AFTER NUMBERS (fixed code, api.py post-fix, 3 runs) ---
Run 1: total=0.489s  median_gap_a=0.024s  median_gap_b=0.024s
Run 2: total=0.510s  median_gap_a=0.025s  median_gap_b=0.025s
Run 3: total=0.490s  median_gap_a=0.025s  median_gap_b=0.024s
Each stream's own median gap now matches the configured 0.02s delay much
more closely (~1.2-1.25x, down from ~2.3-2.45x) -- the other request's
work is no longer stealing this one's turn -- and total wall-clock
(~0.49-0.51s) is close to what ONE request takes alone (~0.4s + fixed
overhead), not the ~0.94-0.99s two serialized requests took before the
fix.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
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

# 20 tokens of 15 chars (300 chars total) comfortably crosses the agent
# loop's 64-char guard buffer many times over, so each request emits ~18
# separate SSE chunks instead of one lump at the very end -- enough data
# points to measure steady-state throughput, not just start/end time.
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


def _median_steady_state_gap(timestamps: list[float]) -> float:
    """Median gap between consecutive chunks, i.e. this stream's own
    steady-state throughput, independent of when it happened to start.
    """
    gaps = [b - a for a, b in zip(timestamps, timestamps[1:], strict=False)]
    return statistics.median(gaps)


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
    actual measured before/after numbers and why total wall-clock and
    per-stream throughput -- not raw chunk-range overlap -- are the
    assertions that actually discriminate serialized from concurrent.
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

    assert len(timestamps_a) >= 10, f"Request A got too few chunks: {timestamps_a}"
    assert len(timestamps_b) >= 10, f"Request B got too few chunks: {timestamps_b}"

    # (a) Each stream's own steady-state throughput (median gap between
    # its consecutive chunks) must be close to the configured per-token
    # delay. If the two requests are still taking turns on one blocked
    # thread, each one's own gap comes out close to DOUBLE the configured
    # delay (see module docstring for the measured before/after ratios).
    median_gap_a = _median_steady_state_gap(timestamps_a)
    median_gap_b = _median_steady_state_gap(timestamps_b)
    max_undegraded_gap = _DELAY_SECONDS * 1.6
    assert median_gap_a < max_undegraded_gap, (
        f"Request A's median inter-chunk gap ({median_gap_a:.3f}s) is far "
        f"above the configured per-token delay ({_DELAY_SECONDS}s): it "
        f"looks like request A is taking turns with request B on one "
        f"blocked thread instead of progressing on its own."
    )
    assert median_gap_b < max_undegraded_gap, (
        f"Request B's median inter-chunk gap ({median_gap_b:.3f}s) is far "
        f"above the configured per-token delay ({_DELAY_SECONDS}s): it "
        f"looks like request B is taking turns with request A on one "
        f"blocked thread instead of progressing on its own."
    )

    # (b) Total wall-clock for both concurrent requests is close to
    # max(A, B) (~ the time one request takes alone), not close to A + B.
    expected_solo_duration = len(_TOKENS) * _DELAY_SECONDS
    assert total_wall_clock < expected_solo_duration * 1.5, (
        f"total_wall_clock={total_wall_clock:.3f}s is not close to a "
        f"single request's own duration (~{expected_solo_duration:.3f}s); "
        f"it looks like the two requests ran serially instead of "
        f"concurrently."
    )
