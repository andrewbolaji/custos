"""Tool registry for the agent loop.

Registers Tool implementations, generates Claude tool-use schemas, and
provides lookup by name. Each tool declares side_effectful: bool so the
agent loop can gate execution.
"""

from __future__ import annotations

from typing import Any

from custos.interfaces import Tool


class ToolRegistry:
    """Registry of available tools, indexed by name."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool. Raises if a tool with the same name exists."""
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    @property
    def tools(self) -> dict[str, Tool]:
        return dict(self._tools)

    def to_claude_tools(self) -> list[dict[str, Any]]:
        """Generate Claude API tool-use schemas for all registered tools.

        Returns the list of tool definitions in the format expected by
        anthropic.messages.create(tools=[...]).
        """
        schemas = []
        for tool in self._tools.values():
            schemas.append({
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            })
        return schemas
