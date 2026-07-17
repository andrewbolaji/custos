"""Tests for built-in tools.

Tests that corpus-touching tools route through the permission-filtered
retriever and respect access control (T5).
"""

from __future__ import annotations

from typing import Any

from custos.interfaces import Chunk, Retriever
from custos.tools.file_ticket import FileTicketTool
from custos.tools.search_documents import SearchDocumentsTool
from custos.tools.send_email import SendEmailTool
from custos.tools.summarize_section import SummarizeSectionTool


class FakeRetriever(Retriever):
    """Test double that records calls and returns controlled results."""

    def __init__(self, results: list[Chunk] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._results = results or []

    def retrieve(
        self,
        query: str,
        user_permissions: list[str],
        k: int = 5,
    ) -> list[Chunk]:
        self.calls.append({
            "query": query,
            "user_permissions": user_permissions,
            "k": k,
        })
        return self._results


def _make_chunk(
    chunk_id: str = "c1",
    permissions: list[str] | None = None,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id="doc-1",
        text="Sample content.",
        section_path=["Section"],
        char_start=0,
        char_end=15,
        permissions=permissions or ["general"],
    )


class TestSearchDocumentsTool:
    def test_is_read_only(self) -> None:
        tool = SearchDocumentsTool(FakeRetriever(), ["general"])
        assert tool.side_effectful is False

    def test_passes_user_permissions_to_retriever(self) -> None:
        retriever = FakeRetriever()
        tool = SearchDocumentsTool(retriever, ["general", "hr"])
        tool.run({"query": "test"})

        assert len(retriever.calls) == 1
        assert retriever.calls[0]["user_permissions"] == ["general", "hr"]

    def test_general_user_permissions_only(self) -> None:
        """A general user's tool call does NOT get hr/finance permissions."""
        retriever = FakeRetriever()
        tool = SearchDocumentsTool(retriever, ["general"])
        tool.run({"query": "salary information"})

        assert retriever.calls[0]["user_permissions"] == ["general"]

    def test_empty_query_returns_error(self) -> None:
        tool = SearchDocumentsTool(FakeRetriever(), ["general"])
        result = tool.run({"query": ""})
        assert "Error" in str(result.output)

    def test_no_results_returns_message(self) -> None:
        tool = SearchDocumentsTool(FakeRetriever(results=[]), ["general"])
        result = tool.run({"query": "nonexistent"})
        assert "No relevant documents" in str(result.output)

    def test_results_include_chunk_ids(self) -> None:
        chunk = _make_chunk("test_chunk_1")
        tool = SearchDocumentsTool(FakeRetriever([chunk]), ["general"])
        result = tool.run({"query": "test"})
        assert "test_chunk_1" in str(result.output)

    def test_has_input_schema(self) -> None:
        tool = SearchDocumentsTool(FakeRetriever(), ["general"])
        schema = tool.input_schema
        assert schema["type"] == "object"
        assert "query" in schema["properties"]


class TestSummarizeSectionTool:
    def test_is_read_only(self) -> None:
        tool = SummarizeSectionTool(FakeRetriever(), ["general"])
        assert tool.side_effectful is False

    def test_passes_user_permissions_to_retriever(self) -> None:
        retriever = FakeRetriever()
        tool = SummarizeSectionTool(retriever, ["hr"])
        tool.run({"topic": "PTO policy"})

        assert retriever.calls[0]["user_permissions"] == ["hr"]

    def test_empty_topic_returns_error(self) -> None:
        tool = SummarizeSectionTool(FakeRetriever(), ["general"])
        result = tool.run({"topic": ""})
        assert "Error" in str(result.output)

    def test_has_input_schema(self) -> None:
        tool = SummarizeSectionTool(FakeRetriever(), ["general"])
        schema = tool.input_schema
        assert schema["type"] == "object"
        assert "topic" in schema["properties"]


class TestSendEmailTool:
    def test_is_side_effectful(self) -> None:
        tool = SendEmailTool()
        assert tool.side_effectful is True

    def test_result_is_simulated(self) -> None:
        tool = SendEmailTool()
        result = tool.run({"to": "a@example.com", "subject": "Hi", "body": "Hello"})
        assert result.simulated is True
        assert "(simulated)" in str(result.output)

    def test_has_input_schema(self) -> None:
        tool = SendEmailTool()
        schema = tool.input_schema
        assert "to" in schema["properties"]
        assert "subject" in schema["properties"]
        assert "body" in schema["properties"]

    def test_name(self) -> None:
        assert SendEmailTool().name == "send_email"


class TestFileTicketTool:
    def test_is_side_effectful(self) -> None:
        tool = FileTicketTool()
        assert tool.side_effectful is True

    def test_result_is_simulated(self) -> None:
        tool = FileTicketTool()
        result = tool.run({"title": "Fix leak", "description": "Kitchen"})
        assert result.simulated is True
        assert "(simulated)" in str(result.output)

    def test_has_input_schema(self) -> None:
        tool = FileTicketTool()
        schema = tool.input_schema
        assert "title" in schema["properties"]
        assert "description" in schema["properties"]

    def test_name(self) -> None:
        assert FileTicketTool().name == "file_ticket"

    def test_default_priority(self) -> None:
        tool = FileTicketTool()
        result = tool.run({"title": "Test", "description": "Test desc"})
        assert "medium" in str(result.output)
