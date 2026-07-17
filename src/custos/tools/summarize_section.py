"""Summarize section tool -- read-only, uses the permission-filtered retriever.

Searches for a specific document section and returns the matching excerpts
for the LLM to summarize. Routes through the SAME permission-filtered
retriever, so the T5 access-control gate holds here too.
"""

from __future__ import annotations

from typing import Any

from custos.interfaces import Chunk, Retriever, Tool, ToolResult


class SummarizeSectionTool(Tool):
    """Retrieve a specific document section for summarization."""

    def __init__(self, retriever: Retriever, user_permissions: list[str]) -> None:
        self._retriever = retriever
        self._user_permissions = user_permissions

    @property
    def name(self) -> str:
        return "summarize_section"

    @property
    def description(self) -> str:
        return (
            "Retrieve a specific document section so you can summarize it. "
            "Use this when the user asks for a summary of a particular topic, "
            "policy, or document section. Returns the relevant excerpts."
        )

    @property
    def side_effectful(self) -> bool:
        return False

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "The topic or section name to retrieve and summarize."
                    ),
                },
            },
            "required": ["topic"],
        }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        """Retrieve section content with the current user's permissions."""
        topic = arguments.get("topic", "")
        if not topic:
            return ToolResult(
                tool_name=self.name,
                output="Error: topic is required.",
            )

        chunks: list[Chunk] = self._retriever.retrieve(
            query=topic,
            user_permissions=self._user_permissions,
            k=5,
        )

        if not chunks:
            return ToolResult(
                tool_name=self.name,
                output="No documents found for this topic.",
            )

        lines = []
        for chunk in chunks:
            path = " > ".join(chunk.section_path)
            lines.append(
                f"[chunk_id: {chunk.chunk_id}]\n"
                f"Source: {chunk.doc_id} > {path}\n"
                f"{chunk.text}\n---"
            )

        return ToolResult(
            tool_name=self.name,
            output="\n".join(lines),
        )
