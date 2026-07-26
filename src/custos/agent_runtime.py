"""Agent runtime selection.

CUSTOS_AGENT_RUNTIME picks between "native" (default, AgentLoop) and
"langgraph" (LangGraphAgentLoop). This module is the only place runtime
selection happens; callers (api.py, evals/suites/action_gating.py) depend
only on the AgentLoopProtocol shape and never import a concrete runtime
directly, matching the CUSTOS_VECTOR_BACKEND / vector_store_config.py
pattern for the vector store.

See docs/decisions/006-agent-runtime.md for why a second implementation
exists at all and what the comparison found.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Protocol

from custos.agent_loop import DEFAULT_MAX_STEPS, DEFAULT_TIMEOUT_SECONDS, AgentLoop

if TYPE_CHECKING:
    from collections.abc import Generator

    from custos.agent_loop import AgentEvent, AgentResult
    from custos.llm import ClaudeLLM, PromptParts
    from custos.pending_actions import PendingActionStore
    from custos.tool_registry import ToolRegistry

_RUNTIMES = ("native", "langgraph")


class AgentLoopProtocol(Protocol):
    """The public surface both AgentLoop and LangGraphAgentLoop implement.

    Structural typing (not inheritance) on purpose: the native AgentLoop
    is not modified to fit this, so this Protocol is written to match its
    existing signature exactly, not the other way around.
    """

    def run(
        self,
        prompt_parts: PromptParts,
        user_query: str,
        *,
        history: list[dict[str, Any]] | None = None,
    ) -> AgentResult: ...

    def run_streaming(
        self,
        prompt_parts: PromptParts,
        user_query: str,
        *,
        session_id: str = "",
        pending_store: PendingActionStore | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> Generator[AgentEvent, None, None]: ...

    @property
    def max_steps(self) -> int: ...

    @property
    def timeout_seconds(self) -> float: ...


def build_agent_loop(
    llm: ClaudeLLM,
    registry: ToolRegistry,
    *,
    max_steps: int = DEFAULT_MAX_STEPS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> AgentLoopProtocol:
    """Construct the agent loop implementation selected by CUSTOS_AGENT_RUNTIME.

    Defaults to "native" (AgentLoop), the hand-rolled implementation that
    remains the default in production. "langgraph" selects
    LangGraphAgentLoop, a second implementation built on langgraph.graph.StateGraph
    that must satisfy the same THREAT_MODEL.md controls -- proven, not
    assumed, by running the same eval suites against both.
    """
    runtime = os.environ.get("CUSTOS_AGENT_RUNTIME", "native").strip().lower()

    if runtime == "native":
        return AgentLoop(
            llm=llm,
            registry=registry,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
        )

    if runtime == "langgraph":
        from custos.agent_loop_langgraph import LangGraphAgentLoop

        return LangGraphAgentLoop(
            llm=llm,
            registry=registry,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
        )

    raise ValueError(
        f"Unknown CUSTOS_AGENT_RUNTIME={runtime!r}; expected one of {_RUNTIMES}."
    )
