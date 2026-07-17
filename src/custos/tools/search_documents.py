"""Search documents tool -- read-only, uses the permission-filtered retriever.

This tool re-runs retrieval with a different query than the user's original
question. It routes through the SAME permission-filtered retriever with the
CURRENT user's permissions. It is a new access-control path and the T5 gate
holds here: a general user cannot use this tool to access HR or finance docs.
"""

from __future__ import annotations

from typing import Any

from custos.interfaces import Chunk, Retriever, Tool, ToolResult


class SearchDocumentsTool(Tool):
    """Search the document corpus for information on a specific topic."""

    def __init__(self, retriever: Retriever, user_permissions: list[str]) -> None:
        self._retriever = retriever
        self._user_permissions = user_permissions

    @property
    def name(self) -> str:
        return "search_documents"

    @property
    def description(self) -> str:
        return (
            "Search the business document corpus for information on a specific "
            "topic. Use this when you need to find additional information beyond "
            "the initially retrieved excerpts. Returns relevant document excerpts."
        )

    @property
    def side_effectful(self) -> bool:
        return False

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to find relevant documents.",
                },
            },
            "required": ["query"],
        }

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        """Search with the current user's permissions."""
        query = arguments.get("query", "")
        if not query:
            return ToolResult(
                tool_name=self.name,
                output="Error: query is required.",
            )

        chunks: list[Chunk] = self._retriever.retrieve(
            query=query,
            user_permissions=self._user_permissions,
            k=5,
        )

        if not chunks:
            return ToolResult(
                tool_name=self.name,
                output="No relevant documents found for this query.",
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
