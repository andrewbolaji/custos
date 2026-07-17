"""File ticket tool -- simulated, side-effectful.

This tool is ALWAYS simulated. It does not create real tickets. The response
includes "(simulated)" and the agent must relay that label to the user.

Side-effectful: the agent loop will NOT execute this tool without explicit
user confirmation via the PendingAction flow.
"""

from __future__ import annotations

from typing import Any

from custos.interfaces import Tool, ToolResult


class FileTicketTool(Tool):
    """Simulate filing a support or maintenance ticket."""

    @property
    def name(self) -> str:
        return "file_ticket"

    @property
    def description(self) -> str:
        return (
            "File a support or maintenance ticket. Use this tool when the "
            "user asks to create a ticket, report an issue, or request "
            "maintenance. The system will handle confirmation before filing."
        )

    @property
    def side_effectful(self) -> bool:
        return True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title for the ticket.",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed description of the issue or request.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Ticket priority level.",
                },
            },
            "required": ["title", "description"],
        }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        """Simulate filing a ticket. Always returns simulated=True."""
        title = arguments.get("title", "")
        priority = arguments.get("priority", "medium")

        return ToolResult(
            tool_name=self.name,
            output=(
                f"Ticket \"{title}\" (priority: {priority}) has been filed. "
                f"(simulated)"
            ),
            simulated=True,
        )
