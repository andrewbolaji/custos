"""Agent loop with tool use, bounded execution, and injection-safe output
handling -- built on langgraph.graph.StateGraph.

This is a SECOND implementation of the same contract agent_loop.AgentLoop
implements (see that module's docstring for the security invariants both
must hold). It exists to measure LangGraph against the hand-rolled loop,
not to replace it; selection is CUSTOS_AGENT_RUNTIME (native default).
See docs/decisions/006-agent-runtime.md for the comparison and findings.

DELIBERATELY NOT USED: langgraph.prebuilt.create_react_agent / ToolNode.
tests/test_langgraph_prebuilt_defeats_gate.py demonstrates, against a real
mocked tool_use response, that LangGraph's own prebuilt tool-execution path
(ToolNode + tools_condition, the shape LangGraph's own "Add tools" tutorial
teaches) executes a side-effectful tool immediately with no confirmation
gate. create_react_agent's own docstring says it "uses ToolNode internally
with sensible defaults," so it inherits the same behavior. Using either
here would silently defeat THREAT_MODEL.md T6. The graph below hand-writes
its own gating node (_node_gate_and_execute) instead, reusing the exact
per-tool logic agent_loop.AgentLoop.run/run_streaming implement, so both
runtimes are provably equivalent rather than assumed equivalent.

Also deliberately not used: LangGraph's checkpointer / persistent memory.
Conversation history is client-supplied per turn, exactly like the native
loop (api.py trims and forwards `history` on every request) -- adopting
server-side checkpointed state would change a trust boundary THREAT_MODEL.md
explicitly defers to a Phase-4-auth ROADMAP item. This graph is stateless
between top-level invocations, matching native's design, not LangGraph's.

State machine (mirrors AgentLoop's run()/run_streaming() exactly -- see
docs/decisions/006-agent-runtime.md for the full state map both were
derived from):

    check_limits -> (limit_hit | call_model)
    call_model   -> (finalize | gate_and_execute)
    gate_and_execute -> check_limits   (loops back)
    finalize     -> END
    limit_hit    -> END

check_limits enforces the timeout bound every cycle and the max_steps bound
via an explicit state counter -- the real T7 control, exactly like native's
`for step in range(max_steps)` + elapsed-time check. LangGraph's own
recursion_limit is set well above what max_steps could ever require, purely
as a redundant backstop (defense in depth, not the control itself).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, TypedDict

import anthropic
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph

from custos.agent_loop import (
    _CITATIONS_FENCE_RE,
    _GUARD_SIZE,
    DEFAULT_MAX_STEPS,
    DEFAULT_TIMEOUT_SECONDS,
    AgentEvent,
    AgentResult,
    _clean_guard_text,
    _wrap_tool_output,
)
from custos.interfaces import ToolCall, ToolResult
from custos.llm import PromptParts, resolve_response

if TYPE_CHECKING:
    from collections.abc import Generator

    from custos.llm_config import AnyLLM
    from custos.pending_actions import PendingActionStore
    from custos.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class _GraphState(TypedDict):
    """Graph state. Plain anthropic-wire-format dicts, not LangChain
    BaseMessage -- this graph calls the raw anthropic client directly
    (no langchain-anthropic model wrapper), so the runtime comparison in
    the ADR isolates LangGraph's own orchestration cost from LangChain's
    message-translation cost.
    """

    messages: list[dict[str, Any]]
    step: int
    tool_use_blocks: list[dict[str, Any]]
    text_parts: list[str]
    pending_assistant_content: list[Any]
    accumulated_raw_text: str
    streamed_text_joined: str
    limit_reason: str
    elapsed: float


class LangGraphAgentLoop:
    """Multi-turn agent loop with tool use and bounded execution, built on
    a langgraph.graph.StateGraph. Same public contract as AgentLoop.
    """

    def __init__(
        self,
        llm: AnyLLM,
        registry: ToolRegistry,
        *,
        max_steps: int = DEFAULT_MAX_STEPS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._max_steps = max_steps
        self._timeout_seconds = timeout_seconds
        self._tools = registry.to_claude_tools()
        self._graph = self._build_graph()

        # Per-call state, set at the top of run()/run_streaming(). Safe as
        # instance attributes because, exactly like AgentLoop, one instance
        # is constructed fresh per request (see agent_runtime.build_agent_loop
        # call sites in api.py) and run()/run_streaming() are not called
        # concurrently on the same instance.
        self._streaming = False
        self._session_id = ""
        self._pending_store: PendingActionStore | None = None
        self._prompt_parts: PromptParts | None = None
        self._system = ""
        self._start_time = 0.0
        self._events: list[AgentEvent] = []
        self._tool_results: list[ToolResult] = []
        self._final_text = ""
        self._final_citations: list[Any] = []
        self._final_refused = False

    @property
    def max_steps(self) -> int:
        return self._max_steps

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_graph(self) -> Any:
        graph = StateGraph(_GraphState)
        graph.add_node("check_limits", self._node_check_limits)
        graph.add_node("call_model", self._node_call_model)
        graph.add_node("gate_and_execute", self._node_gate_and_execute)
        graph.add_node("finalize", self._node_finalize)
        graph.add_node("limit_hit", self._node_limit_hit)

        graph.set_entry_point("check_limits")
        graph.add_conditional_edges(
            "check_limits",
            self._route_after_limits,
            {"call_model": "call_model", "limit_hit": "limit_hit"},
        )
        graph.add_conditional_edges(
            "call_model",
            self._route_after_model,
            {"finalize": "finalize", "gate_and_execute": "gate_and_execute"},
        )
        graph.add_edge("gate_and_execute", "check_limits")
        graph.add_edge("finalize", END)
        graph.add_edge("limit_hit", END)
        return graph.compile()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def run(
        self,
        prompt_parts: PromptParts,
        user_query: str,
        *,
        history: list[dict[str, Any]] | None = None,
    ) -> AgentResult:
        """Execute the agent loop synchronously. See AgentLoop.run."""
        self._reset_for_call(
            streaming=False,
            prompt_parts=prompt_parts,
            session_id="",
            pending_store=None,
        )
        initial_state = self._initial_state(history, user_query)
        self._graph.invoke(
            initial_state,
            config={"recursion_limit": self._recursion_limit()},
        )
        return AgentResult(
            text=self._final_text,
            citations=self._final_citations,
            refused=self._final_refused,
            events=self._events,
            tool_results=self._tool_results,
        )

    def run_streaming(
        self,
        prompt_parts: PromptParts,
        user_query: str,
        *,
        session_id: str = "",
        pending_store: PendingActionStore | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> Generator[AgentEvent, None, None]:
        """Execute the agent loop with real token streaming. See
        AgentLoop.run_streaming.

        Uses LangGraph's own custom-stream mode (get_stream_writer inside
        call_model / gate_and_execute / finalize / limit_hit) so events
        are forwarded live, node-execution-by-node-execution, not buffered
        until the whole graph finishes.
        """
        self._reset_for_call(
            streaming=True,
            prompt_parts=prompt_parts,
            session_id=session_id,
            pending_store=pending_store,
        )
        initial_state = self._initial_state(history, user_query)
        yield from self._graph.stream(
            initial_state,
            stream_mode="custom",
            config={"recursion_limit": self._recursion_limit()},
        )

    def _reset_for_call(
        self,
        *,
        streaming: bool,
        prompt_parts: PromptParts,
        session_id: str,
        pending_store: PendingActionStore | None,
    ) -> None:
        self._streaming = streaming
        self._session_id = session_id
        self._pending_store = pending_store
        self._prompt_parts = prompt_parts
        self._system = prompt_parts.system
        self._start_time = time.monotonic()
        self._events = []
        self._tool_results = []
        self._final_text = ""
        self._final_citations = []
        self._final_refused = False

    def _initial_state(
        self, history: list[dict[str, Any]] | None, user_query: str
    ) -> _GraphState:
        return _GraphState(
            messages=[*(history or []), {"role": "user", "content": user_query}],
            step=0,
            tool_use_blocks=[],
            text_parts=[],
            pending_assistant_content=[],
            accumulated_raw_text="",
            streamed_text_joined="",
            limit_reason="",
            elapsed=0.0,
        )

    def _recursion_limit(self) -> int:
        """Backstop only. The real T7 bound is the explicit step counter
        checked in _node_check_limits; this just keeps LangGraph's own
        default (25) from tripping before that counter does on a large
        max_steps, and is set generously above what max_steps could ever
        require (each step is 3 node visits: check_limits, call_model,
        gate_and_execute).
        """
        return (self._max_steps * 4) + 20

    def _emit(self, event: AgentEvent) -> None:
        """Record an event for the sync run() result AND, when streaming,
        push it live via LangGraph's custom-stream writer. get_stream_writer()
        is a documented no-op outside of stream_mode="custom" (verified: it
        does not raise during .invoke()), so this is safe to call in both
        run() and run_streaming() without branching on self._streaming here.
        """
        self._events.append(event)
        if self._streaming:
            get_stream_writer()(event)

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    def _node_check_limits(self, state: _GraphState) -> dict[str, Any]:
        elapsed = time.monotonic() - self._start_time
        if elapsed >= self._timeout_seconds:
            return {"limit_reason": "timeout", "elapsed": elapsed}
        if state["step"] >= self._max_steps:
            return {"limit_reason": "max_steps"}
        return {"limit_reason": ""}

    def _route_after_limits(self, state: _GraphState) -> str:
        return "limit_hit" if state["limit_reason"] else "call_model"

    def _route_after_model(self, state: _GraphState) -> str:
        return "gate_and_execute" if state["tool_use_blocks"] else "finalize"

    def _node_call_model(self, state: _GraphState) -> dict[str, Any]:
        self._llm.notify_api_call()
        tools_arg = self._tools if self._tools else anthropic.NOT_GIVEN
        if not self._streaming:
            return self._call_model_sync(state, tools_arg)
        return self._call_model_streaming(state, tools_arg)

    def _call_model_sync(self, state: _GraphState, tools_arg: Any) -> dict[str, Any]:
        response = self._llm.client.messages.create(
            model=self._llm.model,
            max_tokens=self._llm.max_tokens,
            temperature=self._llm.temperature,
            system=self._system,
            messages=state["messages"],  # type: ignore[arg-type]
            tools=tools_arg,
        )
        text_parts: list[str] = []
        tool_use_blocks: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_use_blocks.append(
                    {"id": block.id, "name": block.name, "input": block.input}
                )
        return {
            "step": state["step"] + 1,
            "text_parts": text_parts,
            "tool_use_blocks": tool_use_blocks,
            "pending_assistant_content": response.content,
        }

    def _call_model_streaming(self, state: _GraphState, tools_arg: Any) -> dict[str, Any]:
        writer = get_stream_writer()
        accumulated_text: list[str] = []
        streamed_text: list[str] = []
        guard = ""
        tool_use_detected = False
        fence_hit = False

        with self._llm.client.messages.stream(
            model=self._llm.model,
            max_tokens=self._llm.max_tokens,
            temperature=self._llm.temperature,
            system=self._system,
            messages=state["messages"],  # type: ignore[arg-type]
            tools=tools_arg,
        ) as stream:
            for event in stream:
                if (
                    event.type == "content_block_start"
                    and hasattr(event.content_block, "type")
                    and event.content_block.type == "tool_use"
                ):
                    tool_use_detected = True
                    if guard and not fence_hit:
                        cleaned = _clean_guard_text(guard)
                        if cleaned:
                            writer(AgentEvent(kind="text_delta", data={"text": cleaned}))
                            streamed_text.append(cleaned)
                        guard = ""
                    continue

                if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                    token = event.delta.text
                    accumulated_text.append(token)

                    if tool_use_detected or fence_hit:
                        continue

                    guard += token

                    if _CITATIONS_FENCE_RE.search(guard):
                        fence_pos = guard.index("```citations")
                        pre_fence = guard[:fence_pos]
                        if pre_fence:
                            cleaned = _clean_guard_text(pre_fence)
                            if cleaned:
                                writer(AgentEvent(kind="text_delta", data={"text": cleaned}))
                                streamed_text.append(cleaned)
                        fence_hit = True
                        guard = ""
                        continue

                    if len(guard) > _GUARD_SIZE:
                        emit = guard[:-_GUARD_SIZE]
                        guard = guard[-_GUARD_SIZE:]
                        cleaned = _clean_guard_text(emit)
                        if cleaned:
                            writer(AgentEvent(kind="text_delta", data={"text": cleaned}))
                            streamed_text.append(cleaned)

            final_message = stream.get_final_message()

        if guard and not fence_hit and not tool_use_detected:
            cleaned = _clean_guard_text(guard)
            if cleaned:
                writer(AgentEvent(kind="text_delta", data={"text": cleaned}))
                streamed_text.append(cleaned)

        tool_use_blocks: list[dict[str, Any]] = []
        for block in final_message.content:
            if block.type == "tool_use":
                tool_use_blocks.append(
                    {"id": block.id, "name": block.name, "input": block.input}
                )

        return {
            "step": state["step"] + 1,
            "text_parts": [],
            "tool_use_blocks": tool_use_blocks,
            "pending_assistant_content": final_message.content,
            "accumulated_raw_text": "".join(accumulated_text),
            "streamed_text_joined": "".join(streamed_text),
        }

    def _node_gate_and_execute(self, state: _GraphState) -> dict[str, Any]:
        messages = [
            *state["messages"],
            {"role": "assistant", "content": state["pending_assistant_content"]},
        ]
        tool_result_contents: list[dict[str, Any]] = []

        for tu in state["tool_use_blocks"]:
            tool = self._registry.get(tu["name"])
            if tool is None:
                logger.warning("Model requested unknown tool: %s", tu["name"])
                tool_result_contents.append({
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": _wrap_tool_output(
                        f"Error: unknown tool '{tu['name']}'."
                    ),
                })
                continue

            call = ToolCall(
                tool_name=tu["name"],
                arguments=tu["input"],
                side_effectful=tool.side_effectful,
            )

            if tool.side_effectful:
                action_id = ""
                if self._pending_store is not None and self._session_id:
                    pending = self._pending_store.create(
                        session_id=self._session_id,
                        tool_name=call.tool_name,
                        arguments=call.arguments,
                    )
                    action_id = pending.action_id

                self._emit(AgentEvent(
                    kind="confirm_action",
                    data={
                        "tool_name": call.tool_name,
                        "action_id": action_id,
                        "arguments": call.arguments,
                    },
                ))
                logger.info(
                    "Side-effectful tool blocked pending confirmation: %s",
                    call.tool_name,
                )
                tool_result_contents.append({
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": _wrap_tool_output(
                        f"Action '{call.tool_name}' requires user confirmation "
                        f"before execution. The action has NOT been performed. "
                        f"A confirmation card with the full details is shown "
                        f"to the user. Respond with ONE brief sentence like "
                        f"'I've drafted that for your review. Approve or "
                        f"reject below.' Do NOT restate the action details."
                    ),
                })
                continue

            self._emit(AgentEvent(kind="tool_use", data={"tool_name": call.tool_name}))

            try:
                result = tool.run(call.arguments)
            except Exception:
                logger.exception("Tool execution failed: %s", call.tool_name)
                result = ToolResult(
                    tool_name=call.tool_name,
                    output=f"Error: tool '{call.tool_name}' failed.",
                )

            self._emit(AgentEvent(
                kind="tool_result",
                data={"tool_name": result.tool_name, "simulated": result.simulated},
            ))
            self._tool_results.append(result)

            output_str = str(result.output)
            if result.simulated:
                output_str += "\n(simulated)"
            tool_result_contents.append({
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": _wrap_tool_output(output_str),
            })

        messages.append({"role": "user", "content": tool_result_contents})
        return {"messages": messages}

    def _node_finalize(self, state: _GraphState) -> dict[str, Any]:
        assert self._prompt_parts is not None
        if not self._streaming:
            full_text = "\n".join(state["text_parts"])
            answer = resolve_response(full_text, self._prompt_parts.chunk_lookup)
            self._emit(AgentEvent(kind="text", data={"text": answer.text}))
            self._final_text = answer.text
            self._final_citations = list(answer.citations)
            self._final_refused = answer.refused
            return {}

        full_text = state["accumulated_raw_text"]
        answer = resolve_response(full_text, self._prompt_parts.chunk_lookup)
        already_streamed = state["streamed_text_joined"]
        if already_streamed.strip() != answer.text.strip():
            self._emit(AgentEvent(kind="text_replace", data={"text": answer.text}))
        if answer.citations:
            self._emit(AgentEvent(kind="citations", data={"citations": answer.citations}))
        if answer.refused:
            self._emit(AgentEvent(kind="refused", data={"text": answer.text}))
        return {}

    def _node_limit_hit(self, state: _GraphState) -> dict[str, Any]:
        if state["limit_reason"] == "timeout":
            self._emit(AgentEvent(
                kind="limit_hit",
                data={"reason": "timeout", "elapsed": state["elapsed"]},
            ))
            logger.warning(
                "Agent loop timeout after %.1fs at step %d",
                state["elapsed"], state["step"],
            )
        else:
            self._emit(AgentEvent(
                kind="limit_hit",
                data={"reason": "max_steps", "steps": self._max_steps},
            ))
            logger.warning("Agent loop hit max steps: %d", self._max_steps)

        if not self._streaming:
            self._final_text = (
                "I was not able to complete the request within the allowed number "
                "of steps. Please try rephrasing your question."
            )
            self._final_citations = []
            self._final_refused = True
        return {}
