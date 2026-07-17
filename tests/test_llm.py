"""Tests for citation ID resolution and abstention logic.

These tests do NOT call the Claude API. They test the resolution and
parsing logic using synthetic LLM responses.
"""

from __future__ import annotations

from custos.interfaces import Chunk
from custos.llm import ClaudeLLM


def _make_chunk(chunk_id: str, doc_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        text=text,
        section_path=["Section"],
        char_start=0,
        char_end=len(text),
        permissions=["general"],
    )


class TestCitationResolution:
    """Valid IDs resolve; invalid IDs are dropped."""

    def test_valid_id_resolves(self) -> None:
        chunk = _make_chunk("abc_123", "doc-1", "Sample text.")
        lookup = {"abc_123": chunk}
        citations = ClaudeLLM._resolve_citations(["abc_123"], lookup)
        assert len(citations) == 1
        assert citations[0].doc_id == "doc-1"
        assert citations[0].char_start == 0
        assert citations[0].char_end == len("Sample text.")

    def test_invalid_id_dropped(self) -> None:
        chunk = _make_chunk("abc_123", "doc-1", "Sample text.")
        lookup = {"abc_123": chunk}
        citations = ClaudeLLM._resolve_citations(
            ["abc_123", "hallucinated_999"], lookup
        )
        assert len(citations) == 1
        assert citations[0].doc_id == "doc-1"

    def test_duplicate_id_deduped(self) -> None:
        chunk = _make_chunk("abc_123", "doc-1", "Sample text.")
        lookup = {"abc_123": chunk}
        citations = ClaudeLLM._resolve_citations(
            ["abc_123", "abc_123", "abc_123"], lookup
        )
        assert len(citations) == 1

    def test_empty_ids_return_empty(self) -> None:
        citations = ClaudeLLM._resolve_citations([], {})
        assert len(citations) == 0

    def test_all_invalid_ids_return_empty(self) -> None:
        citations = ClaudeLLM._resolve_citations(
            ["fake_1", "fake_2"], {}
        )
        assert len(citations) == 0

    def test_snippet_truncated(self) -> None:
        long_text = "X" * 300
        chunk = _make_chunk("long_1", "doc-1", long_text)
        lookup = {"long_1": chunk}
        citations = ClaudeLLM._resolve_citations(["long_1"], lookup)
        assert len(citations) == 1
        assert len(citations[0].snippet) < len(long_text)
        assert citations[0].snippet.endswith("...")


class TestCitationExtraction:
    """Parse chunk_ids from model output."""

    def test_extracts_from_json_block(self) -> None:
        text = 'Some answer.\n\n```citations\n["chunk_a", "chunk_b"]\n```\n'
        ids = ClaudeLLM._extract_citation_ids(text)
        assert ids == ["chunk_a", "chunk_b"]

    def test_extracts_inline_fallback(self) -> None:
        text = "The answer is X [doc1_chunk1] and Y [doc2_chunk2]."
        ids = ClaudeLLM._extract_citation_ids(text)
        assert "doc1_chunk1" in ids
        assert "doc2_chunk2" in ids

    def test_no_citations_returns_empty(self) -> None:
        text = "Just a plain answer with no citations."
        ids = ClaudeLLM._extract_citation_ids(text)
        assert len(ids) == 0


class TestAbstentionOnEmptyContext:
    """The LLM must refuse when given no context chunks."""

    def test_empty_context_returns_refusal(self) -> None:
        # This test does not call the API. It tests the generate() path
        # for empty context, which returns a refusal without an API call.
        llm = ClaudeLLM.__new__(ClaudeLLM)
        answer = llm.generate(
            system_prompt="test",
            context_chunks=[],
            user_query="What is the PTO policy?",
        )
        assert answer.refused is True
        assert len(answer.citations) == 0
        assert "don't have information" in answer.text.lower()
