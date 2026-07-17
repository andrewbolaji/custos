"""Agent loop with tool use, bounded execution, and injection-safe output handling.

The agent loop is the multi-turn orchestration layer between retrieval and the
final answer. It:

1. Sends the user query + retrieved context + tool definitions to Claude
2. Parses structured tool_use blocks from the response (NEVER text content)
3. Gates side-effectful tools (they require explicit user confirmation)
4. Executes permitted tools and feeds results back as UNTRUSTED DATA
5. Repeats until the model produces a text-only response or limits are hit

SECURITY INVARIANTS:
- Tool calls are parsed ONLY from Claude API's structured tool_use content
  blocks, never from free text. This prevents injected text in documents or
  tool outputs from being interpreted as tool requests.
- Tool outputs are wrapped in [TOOL OUTPUT - UNTRUSTED DATA] envelopes
  before being fed back to the model. They are data, not instructions.
- Side-effectful tools NEVER execute without explicit user approval. The
  hard gate is on execution, not on the model's request. Even if injection
  convinces the model to emit a side-effectful tool_use, it produces a
  pending confirmation and zero execution until approved.
- The loop is bounded by max_steps and timeout_seconds. An injected or
  runaway loop cannot spin indefinitely (threat T7).

ONE IMPLEMENTATION, BOTH ENDPOINTS:
Both /api/chat and /api/chat/stream call the same run() method. The loop
is not forked into two copies. Streaming wraps the same loop with SSE
event emission.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import anthropic

from custos.interfaces import Chunk, Citation, ToolCall, ToolResult
from custos.llm import ClaudeLLM, PromptParts
from custos.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

# Maximum agent steps before forced termination (threat T7)
DEFAULT_MAX_STEPS = 5
# Maximum wall-clock seconds for the entire agent loop (threat T7)
DEFAULT_TIMEOUT_SECONDS = 30


@dataclass
class AgentEvent:
    """An event emitted during agent loop execution.

    Events are consumed by the API layer to produce SSE events for
    streaming, or aggregated for the sync response.
    """

    kind: str  # "tool_use", "tool_result", "text", "limit_hit", "needs_confirmation"
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """The final result of an agent loop execution."""

    text: str
    citations: list[Citation]
    refused: bool
    events: list[AgentEvent]
    tool_results: list[ToolResult]


class AgentLoop:
    """Multi-turn agent loop with tool use and bounded execution.

    This is the single implementation used by both /api/chat and
    /api/chat/stream. The loop emits AgentEvents that the API layer
    can forward as SSE events or collect for a sync response.
    """

    def __init__(
        self,
        llm: ClaudeLLM,
        registry: ToolRegistry,
        *,
        max_steps: int = DEFAULT_MAX_STEPS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._max_steps = max_steps
        self._timeout_seconds = timeout_seconds

    def run(
        self,
        prompt_parts: PromptParts,
        user_query: str,
    ) -> AgentResult:
        """Execute the agent loop synchronously.

        Returns the final AgentResult with text, citations, events,
        and tool results. Side-effectful tool calls are NOT executed;
        they produce a needs_confirmation event instead.
        """
        events: list[AgentEvent] = []
        tool_results: list[ToolResult] = []
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": user_query},
        ]
        tools = self._registry.to_claude_tools()
        start_time = time.monotonic()

        for step in range(self._max_steps):
            # Check timeout
            elapsed = time.monotonic() - start_time
            if elapsed >= self._timeout_seconds:
                events.append(AgentEvent(
                    kind="limit_hit",
                    data={"reason": "timeout", "elapsed": elapsed},
                ))
                logger.warning(
                    "Agent loop timeout after %.1fs at step %d", elapsed, step
                )
                break

            # Call Claude with tools
            response = self._llm.client.messages.create(
                model=self._llm.model,
                max_tokens=self._llm.max_tokens,
                temperature=self._llm.temperature,
                system=prompt_parts.system,
                messages=messages,
                tools=tools if tools else anthropic.NOT_GIVEN,
            )

            # Process the response content blocks
            text_parts: list[str] = []
            tool_use_blocks: list[dict[str, Any]] = []
            tool_result_contents: list[dict[str, Any]] = []

            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_use_blocks.append({
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            # If no tool calls, this is the final answer
            if not tool_use_blocks:
                full_text = "\n".join(text_parts)
                answer = ClaudeLLM.resolve_response(
                    full_text, prompt_parts.chunk_lookup
                )
                events.append(AgentEvent(kind="text", data={"text": answer.text}))
                return AgentResult(
                    text=answer.text,
                    citations=answer.citations,
                    refused=answer.refused,
                    events=events,
                    tool_results=tool_results,
                )

            # Process tool calls
            # Add the assistant's response to messages first
            messages.append({"role": "assistant", "content": response.content})

            for tu in tool_use_blocks:
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
                    # HARD GATE: side-effectful tools do NOT execute.
                    # They produce a needs_confirmation event. The API
                    # layer surfaces this to the user.
                    events.append(AgentEvent(
                        kind="needs_confirmation",
                        data={
                            "tool_name": call.tool_name,
                            "side_effectful": True,
                        },
                    ))
                    logger.info(
                        "Side-effectful tool blocked pending confirmation: %s",
                        call.tool_name,
                    )
                    # Return a refusal to the model so it can continue
                    tool_result_contents.append({
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": _wrap_tool_output(
                            f"Action '{call.tool_name}' requires user confirmation "
                            f"before execution. The action has NOT been performed. "
                            f"Tell the user you need their approval to proceed."
                        ),
                    })
                    continue

                # Read-only tool: execute directly
                events.append(AgentEvent(
                    kind="tool_use",
                    data={"tool_name": call.tool_name},
                ))

                try:
                    result = tool.run(call.arguments)
                except Exception:
                    logger.exception("Tool execution failed: %s", call.tool_name)
                    result = ToolResult(
                        tool_name=call.tool_name,
                        output=f"Error: tool '{call.tool_name}' failed.",
                    )

                simulated_label = " (simulated)" if result.simulated else ""
                events.append(AgentEvent(
                    kind="tool_result",
                    data={
                        "tool_name": result.tool_name,
                        "simulated": result.simulated,
                    },
                ))
                tool_results.append(result)

                # Feed tool output back as UNTRUSTED DATA
                output_str = str(result.output)
                if result.simulated:
                    output_str += "\n(simulated)"
                tool_result_contents.append({
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": _wrap_tool_output(output_str),
                })

            # Add tool results to messages for the next turn
            messages.append({"role": "user", "content": tool_result_contents})

        else:
            # Max steps reached without a final text response
            events.append(AgentEvent(
                kind="limit_hit",
                data={"reason": "max_steps", "steps": self._max_steps},
            ))
            logger.warning("Agent loop hit max steps: %d", self._max_steps)

        # If we exit the loop without returning, produce a fallback
        final_text = (
            "I was not able to complete the request within the allowed number "
            "of steps. Please try rephrasing your question."
        )
        return AgentResult(
            text=final_text,
            citations=[],
            refused=True,
            events=events,
            tool_results=tool_results,
        )

    @property
    def max_steps(self) -> int:
        return self._max_steps

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds


def _wrap_tool_output(output: str) -> str:
    """Wrap tool output in an untrusted-data envelope.

    This framing tells the model to treat the content as data, not
    instructions. It mirrors the same separation used for retrieved
    document chunks in build_prompt().
    """
    return (
        f"[TOOL OUTPUT - UNTRUSTED DATA]\n"
        f"{output}\n"
        f"[END TOOL OUTPUT]"
    )
