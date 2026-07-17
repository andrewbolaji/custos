"""Tests for ToolRegistry."""

from __future__ import annotations

from typing import Any

import pytest

from custos.interfaces import Tool, ToolResult
from custos.tool_registry import ToolRegistry


class FakeReadOnlyTool(Tool):
    @property
    def name(self) -> str:
        return "fake_read"

    @property
    def description(self) -> str:
        return "A fake read-only tool."

    @property
    def side_effectful(self) -> bool:
        return False

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"q": {"type": "string"}}}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(tool_name=self.name, output="result")


class FakeSideEffectTool(Tool):
    @property
    def name(self) -> str:
        return "fake_send"

    @property
    def description(self) -> str:
        return "A fake side-effectful tool."

    @property
    def side_effectful(self) -> bool:
        return True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"to": {"type": "string"}}}

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(tool_name=self.name, output="sent", simulated=True)


class TestToolRegistry:
    def test_register_and_get(self) -> None:
        reg = ToolRegistry()
        tool = FakeReadOnlyTool()
        reg.register(tool)
        assert reg.get("fake_read") is tool

    def test_get_unknown_returns_none(self) -> None:
        reg = ToolRegistry()
        assert reg.get("nonexistent") is None

    def test_duplicate_name_raises(self) -> None:
        reg = ToolRegistry()
        reg.register(FakeReadOnlyTool())
        with pytest.raises(ValueError, match="already registered"):
            reg.register(FakeReadOnlyTool())

    def test_to_claude_tools_schema(self) -> None:
        reg = ToolRegistry()
        reg.register(FakeReadOnlyTool())
        reg.register(FakeSideEffectTool())
        schemas = reg.to_claude_tools()

        assert len(schemas) == 2
        names = {s["name"] for s in schemas}
        assert names == {"fake_read", "fake_send"}

        for s in schemas:
            assert "description" in s
            assert "input_schema" in s

    def test_tools_property_returns_copy(self) -> None:
        reg = ToolRegistry()
        reg.register(FakeReadOnlyTool())
        tools = reg.tools
        tools["injected"] = FakeSideEffectTool()  # type: ignore[assignment]
        assert reg.get("injected") is None  # Original not mutated
