"""Focused tests for LangGraphAgentLoop's security-critical behaviors.

These do NOT call the Claude API; they use mock responses, mirroring the
fixtures in test_agent_loop.py (FakeTextBlock/FakeToolUseBlock/FakeResponse/
FakeStreamContext) so the two test files stay comparable side by side.

This file is NOT a full clone of test_agent_loop.py's 809 lines. The
authoritative parity proof that both runtimes hold the same guarantees is
the 61 deterministic evals run against CUSTOS_AGENT_RUNTIME=native and
=langgraph (see evals/suites/action_gating.py, wired through
custos.agent_runtime.build_agent_loop). This file is the fast local
feedback loop during development: the handful of behaviors that must never
regress, checked directly against LangGraphAgentLoop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

from custos.agent_loop_langgraph import LangGraphAgentLoop
from custos.interfaces import Chunk, Tool, ToolResult
from custos.llm import ClaudeLLM, PromptParts
from custos.pending_actions import PendingActionStore
from custos.tool_registry import ToolRegistry


def _make_chunk(chunk_id: str = "c1_x", text: str = "Test.") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id="doc-1",
        text=text,
        section_path=["Section"],
        char_start=0,
        char_end=len(text),
        permissions=["general"],
    )


def _make_prompt_parts() -> PromptParts:
    return ClaudeLLM.build_prompt("System prompt.", [_make_chunk()])


class ReadOnlyTool(Tool):
    @property
    def name(self) -> str:
        return "lookup"

    @property
    def description(self) -> str:
        return "A lookup tool."

    @property
    def side_effectful(self) -> bool:
        return False

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"q": {"type": "string"}}}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(tool_name=self.name, output=f"Found: {arguments.get('q')}")


class RaisingTool(ReadOnlyTool):
    def run(self, arguments: dict[str, Any]) -> ToolResult:
        raise RuntimeError("simulated tool failure")


class SideEffectTool(Tool):
    def __init__(self) -> None:
        self.executed = False

    @property
    def name(self) -> str:
        return "send_email"

    @property
    def description(self) -> str:
        return "Send an email."

    @property
    def side_effectful(self) -> bool:
        return True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"to": {"type": "string"}}}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        self.executed = True
        return ToolResult(tool_name=self.name, output="sent", simulated=True)


@dataclass
class FakeTextBlock:
    type: str = "text"
    text: str = "The answer is 42."


@dataclass
class FakeToolUseBlock:
    type: str = "tool_use"
    id: str = "tu_001"
    name: str = "lookup"
    input: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.input is None:
            self.input = {"q": "test"}


@dataclass
class FakeResponse:
    content: list[Any] | None = None
    stop_reason: str = "end_turn"

    def __post_init__(self) -> None:
        if self.content is None:
            self.content = [FakeTextBlock()]


def _make_llm() -> ClaudeLLM:
    llm = ClaudeLLM.__new__(ClaudeLLM)
    llm._model = "test"
    llm._max_tokens = 1024
    llm._temperature = 0.1
    llm._client = MagicMock()
    return llm


class TestTextOnly:
    def test_text_only_response_returns_immediately(self) -> None:
        llm = _make_llm()
        llm._client.messages.create.return_value = FakeResponse(
            content=[FakeTextBlock(text="Direct answer, no tools.")]
        )
        registry = ToolRegistry()
        loop = LangGraphAgentLoop(llm=llm, registry=registry)

        result = loop.run(_make_prompt_parts(), "a question")

        assert result.refused is False
        assert "Direct answer" in result.text
        assert llm._client.messages.create.call_count == 1


class TestToolGating:
    def test_read_only_tool_executes(self) -> None:
        llm = _make_llm()
        llm._client.messages.create.side_effect = [
            FakeResponse(content=[FakeToolUseBlock()]),
            FakeResponse(content=[FakeTextBlock(text="Done.")]),
        ]
        tool = ReadOnlyTool()
        registry = ToolRegistry()
        registry.register(tool)
        loop = LangGraphAgentLoop(llm=llm, registry=registry)

        result = loop.run(_make_prompt_parts(), "look something up")

        tool_events = [e for e in result.events if e.kind == "tool_use"]
        assert len(tool_events) == 1
        assert any(e.kind == "tool_result" for e in result.events)
        assert not result.refused

    def test_side_effectful_tool_never_executes(self) -> None:
        llm = _make_llm()
        llm._client.messages.create.side_effect = [
            FakeResponse(content=[
                FakeToolUseBlock(name="send_email", input={"to": "x@x.com"})
            ]),
            FakeResponse(content=[FakeTextBlock(text="Drafted.")]),
        ]
        tool = SideEffectTool()
        registry = ToolRegistry()
        registry.register(tool)
        loop = LangGraphAgentLoop(llm=llm, registry=registry)

        result = loop.run(_make_prompt_parts(), "email someone")

        assert tool.executed is False
        confirm_events = [e for e in result.events if e.kind == "confirm_action"]
        assert len(confirm_events) == 1
        assert confirm_events[0].data["tool_name"] == "send_email"
        # run() (sync) never binds a PendingAction -- matches AgentLoop.run,
        # which does not accept pending_store/session_id at all.
        assert confirm_events[0].data["action_id"] == ""

    def test_unknown_tool_name_does_not_crash(self) -> None:
        llm = _make_llm()
        llm._client.messages.create.side_effect = [
            FakeResponse(content=[FakeToolUseBlock(name="does_not_exist")]),
            FakeResponse(content=[FakeTextBlock(text="Recovered.")]),
        ]
        registry = ToolRegistry()
        loop = LangGraphAgentLoop(llm=llm, registry=registry)

        result = loop.run(_make_prompt_parts(), "call a fake tool")

        assert result.text == "Recovered."
        assert not result.refused


class TestBounds:
    def test_max_steps_enforced(self) -> None:
        llm = _make_llm()
        llm._client.messages.create.return_value = FakeResponse(
            content=[FakeToolUseBlock()]
        )
        registry = ToolRegistry()
        registry.register(ReadOnlyTool())
        loop = LangGraphAgentLoop(llm=llm, registry=registry, max_steps=3)

        result = loop.run(_make_prompt_parts(), "infinite loop")

        assert result.refused is True
        assert llm._client.messages.create.call_count == 3
        limit_events = [e for e in result.events if e.kind == "limit_hit"]
        assert len(limit_events) == 1
        assert limit_events[0].data["reason"] == "max_steps"

    def test_raising_tool_becomes_failed_result_and_stays_bounded(self) -> None:
        llm = _make_llm()
        llm._client.messages.create.return_value = FakeResponse(
            content=[FakeToolUseBlock()]
        )
        registry = ToolRegistry()
        registry.register(RaisingTool())

        result = LangGraphAgentLoop(
            llm=llm, registry=registry, max_steps=2
        ).run(_make_prompt_parts(), "keep calling the failing tool")

        assert result.refused is True
        assert len(result.tool_results) == 2
        assert all("failed" in str(item.output) for item in result.tool_results)
        assert llm._client.messages.create.call_count == 2
        assert any(
            event.kind == "limit_hit" and event.data["reason"] == "max_steps"
            for event in result.events
        )

    def test_timeout_enforced(self) -> None:
        llm = _make_llm()
        llm._client.messages.create.return_value = FakeResponse(
            content=[FakeToolUseBlock()]
        )

        import custos.agent_loop_langgraph as lg

        call_count = 0

        def fake_monotonic() -> float:
            nonlocal call_count
            call_count += 1
            return 0.0 if call_count <= 1 else 100.0

        registry = ToolRegistry()
        registry.register(ReadOnlyTool())
        loop = LangGraphAgentLoop(llm=llm, registry=registry, timeout_seconds=5)

        with patch.object(lg.time, "monotonic", side_effect=fake_monotonic):
            result = loop.run(_make_prompt_parts(), "test")

        assert result.refused is True
        limit_events = [e for e in result.events if e.kind == "limit_hit"]
        assert len(limit_events) == 1
        assert limit_events[0].data["reason"] == "timeout"


class TestCitationPassthrough:
    def test_valid_citation_resolves(self) -> None:
        llm = _make_llm()
        llm._client.messages.create.return_value = FakeResponse(
            content=[FakeTextBlock(
                text='The answer.\n```citations\n["c1_x"]\n```'
            )]
        )
        registry = ToolRegistry()
        loop = LangGraphAgentLoop(llm=llm, registry=registry)

        result = loop.run(_make_prompt_parts(), "a question")

        assert len(result.citations) == 1
        assert result.citations[0].doc_id == "doc-1"
        assert "```citations" not in result.text


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


@dataclass
class FakeDelta:
    text: str


@dataclass
class FakeContentBlock:
    type: str


@dataclass
class FakeStreamEvent:
    type: str
    delta: FakeDelta | None = None
    content_block: FakeContentBlock | None = None


class FakeStreamContext:
    def __init__(self, events: list[FakeStreamEvent], final_message: FakeResponse) -> None:
        self._events = events
        self._final_message = final_message

    @classmethod
    def from_tokens(cls, tokens: list[str], final_message: FakeResponse) -> FakeStreamContext:
        events = [
            FakeStreamEvent(type="content_block_delta", delta=FakeDelta(text=t))
            for t in tokens
        ]
        return cls(events, final_message)

    def __enter__(self) -> FakeStreamContext:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def __iter__(self):  # type: ignore[override]
        yield from self._events

    def get_final_message(self) -> FakeResponse:
        return self._final_message


class TestStreaming:
    def test_answer_text_waits_for_complete_response(self) -> None:
        llm = _make_llm()
        tokens = [
            "The PTO rate is ten days per year for new employees. ",
            "Unused days carry over up to five days.",
        ]
        llm._client.messages.stream.return_value = FakeStreamContext.from_tokens(
            tokens, FakeResponse(content=[FakeTextBlock(text="".join(tokens))])
        )
        registry = ToolRegistry()
        loop = LangGraphAgentLoop(llm=llm, registry=registry)

        events = list(loop.run_streaming(_make_prompt_parts(), "a question"))

        delta_events = [e for e in events if e.kind == "text_delta"]
        assert len(delta_events) == 1
        forwarded = "".join(e.data["text"] for e in delta_events)
        assert forwarded == "".join(tokens)
        assert len([e for e in events if e.kind == "stream_progress"]) == len(tokens)

    def test_pii_never_appears_in_any_client_visible_prefix(self) -> None:
        cases = [
            ("900-55-0000", "[SSN]"),
            ("james.santos@example.org", "[EMAIL]"),
            ("(312) 555-0199", "[PHONE]"),
        ]
        for sensitive, marker in cases:
            raw_answer = f"A long preamble {'x' * 80} contact {sensitive} is private."
            sensitive_start = raw_answer.index(sensitive)
            for cut in range(1, len(sensitive)):
                split = sensitive_start + cut
                tokens = [raw_answer[:split], raw_answer[split:]]
                llm = _make_llm()
                llm._client.messages.stream.return_value = (
                    FakeStreamContext.from_tokens(
                        tokens,
                        FakeResponse(content=[FakeTextBlock(text=raw_answer)]),
                    )
                )

                events = list(
                    LangGraphAgentLoop(
                        llm=llm, registry=ToolRegistry()
                    ).run_streaming(_make_prompt_parts(), "contact?")
                )
                visible = "".join(
                    event.data["text"]
                    for event in events
                    if event.kind == "text_delta"
                )
                for prefix_end in range(len(visible) + 1):
                    assert sensitive not in visible[:prefix_end]
                assert marker in visible
                assert not any(event.kind == "text_replace" for event in events)

    def test_side_effectful_tool_creates_real_pending_action(self) -> None:
        """Unlike run(), run_streaming() with a pending_store + session_id
        must create a real PendingAction and put its action_id on the
        confirm_action event -- matching AgentLoop.run_streaming exactly.
        """
        llm = _make_llm()
        llm._client.messages.stream.side_effect = [
            FakeStreamContext(
                events=[
                    FakeStreamEvent(
                        type="content_block_start",
                        content_block=FakeContentBlock(type="tool_use"),
                    )
                ],
                final_message=FakeResponse(content=[
                    FakeToolUseBlock(name="send_email", input={"to": "x@x.com"})
                ]),
            ),
            # The graph loops back to call_model after gating; this is the
            # model's follow-up turn after receiving the "requires
            # confirmation" tool_result.
            FakeStreamContext.from_tokens(
                ["I've drafted that for your review."],
                FakeResponse(content=[
                    FakeTextBlock(text="I've drafted that for your review.")
                ]),
            ),
        ]
        tool = SideEffectTool()
        registry = ToolRegistry()
        registry.register(tool)
        loop = LangGraphAgentLoop(llm=llm, registry=registry)
        store = PendingActionStore()

        events = list(loop.run_streaming(
            _make_prompt_parts(),
            "email someone",
            session_id="sess-1",
            pending_store=store,
        ))

        assert tool.executed is False
        confirm_events = [e for e in events if e.kind == "confirm_action"]
        assert len(confirm_events) == 1
        action_id = confirm_events[0].data["action_id"]
        assert action_id != ""
        assert store.get(action_id) is not None
        assert store.get(action_id).session_id == "sess-1"  # type: ignore[union-attr]

    def test_raising_tool_stream_becomes_failed_result_and_stays_bounded(self) -> None:
        llm = _make_llm()
        tool_turn = FakeResponse(content=[FakeToolUseBlock()])
        tool_stream = FakeStreamContext(
            events=[
                FakeStreamEvent(
                    type="content_block_start",
                    content_block=FakeContentBlock(type="tool_use"),
                )
            ],
            final_message=tool_turn,
        )
        llm._client.messages.stream.return_value = tool_stream
        registry = ToolRegistry()
        registry.register(RaisingTool())

        events = list(
            LangGraphAgentLoop(
                llm=llm, registry=registry, max_steps=2
            ).run_streaming(_make_prompt_parts(), "keep calling the failing tool")
        )

        assert llm._client.messages.stream.call_count == 2
        assert len([event for event in events if event.kind == "tool_result"]) == 2
        assert any(
            event.kind == "limit_hit" and event.data["reason"] == "max_steps"
            for event in events
        )
