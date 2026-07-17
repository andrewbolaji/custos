"""Send email tool -- simulated, side-effectful.

This tool is ALWAYS simulated. It does not send real emails. The response
includes "(simulated)" and the agent must relay that label to the user.

Side-effectful: the agent loop will NOT execute this tool without explicit
user confirmation via the PendingAction flow.
"""

from __future__ import annotations

from typing import Any

from custos.interfaces import Tool, ToolResult


class SendEmailTool(Tool):
    """Simulate sending an email on behalf of the user."""

    @property
    def name(self) -> str:
        return "send_email"

    @property
    def description(self) -> str:
        return (
            "Send an email to a recipient. This action requires user "
            "confirmation before it can proceed. The email will be "
            "simulated, not actually sent."
        )

    @property
    def side_effectful(self) -> bool:
        return True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "The recipient email address.",
                },
                "subject": {
                    "type": "string",
                    "description": "The email subject line.",
                },
                "body": {
                    "type": "string",
                    "description": "The email body text.",
                },
            },
            "required": ["to", "subject", "body"],
        }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        """Simulate sending an email. Always returns simulated=True."""
        to = arguments.get("to", "")
        subject = arguments.get("subject", "")

        return ToolResult(
            tool_name=self.name,
            output=(
                f"Email to {to} with subject \"{subject}\" has been sent. "
                f"(simulated)"
            ),
            simulated=True,
        )
