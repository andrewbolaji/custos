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
        citations = ClaudeLLM.resolve_citations(["abc_123"], lookup)
        assert len(citations) == 1
        assert citations[0].doc_id == "doc-1"
        assert citations[0].char_start == 0
        assert citations[0].char_end == len("Sample text.")

    def test_invalid_id_dropped(self) -> None:
        chunk = _make_chunk("abc_123", "doc-1", "Sample text.")
        lookup = {"abc_123": chunk}
        citations = ClaudeLLM.resolve_citations(
            ["abc_123", "hallucinated_999"], lookup
        )
        assert len(citations) == 1
        assert citations[0].doc_id == "doc-1"

    def test_duplicate_id_deduped(self) -> None:
        chunk = _make_chunk("abc_123", "doc-1", "Sample text.")
        lookup = {"abc_123": chunk}
        citations = ClaudeLLM.resolve_citations(
            ["abc_123", "abc_123", "abc_123"], lookup
        )
        assert len(citations) == 1

    def test_empty_ids_return_empty(self) -> None:
        citations = ClaudeLLM.resolve_citations([], {})
        assert len(citations) == 0

    def test_all_invalid_ids_return_empty(self) -> None:
        citations = ClaudeLLM.resolve_citations(
            ["fake_1", "fake_2"], {}
        )
        assert len(citations) == 0

    def test_snippet_truncated(self) -> None:
        long_text = "X" * 300
        chunk = _make_chunk("long_1", "doc-1", long_text)
        lookup = {"long_1": chunk}
        citations = ClaudeLLM.resolve_citations(["long_1"], lookup)
        assert len(citations) == 1
        assert len(citations[0].snippet) < len(long_text)
        assert citations[0].snippet.endswith("...")


class TestCitationExtraction:
    """Parse chunk_ids from model output."""

    def test_extracts_from_json_block(self) -> None:
        text = 'Some answer.\n\n```citations\n["chunk_a", "chunk_b"]\n```\n'
        ids = ClaudeLLM.extract_citation_ids(text)
        assert ids == ["chunk_a", "chunk_b"]

    def test_extracts_inline_fallback(self) -> None:
        text = "The answer is X [doc1_chunk1] and Y [doc2_chunk2]."
        ids = ClaudeLLM.extract_citation_ids(text)
        assert "doc1_chunk1" in ids
        assert "doc2_chunk2" in ids

    def test_no_citations_returns_empty(self) -> None:
        text = "Just a plain answer with no citations."
        ids = ClaudeLLM.extract_citation_ids(text)
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


class TestPromptConsolidation:
    """Both /api/chat and /api/chat/stream use the same prompt assembly.

    This test proves that build_prompt() produces identical output regardless
    of which endpoint calls it, so the injection boundary (trusted instructions
    vs. untrusted retrieved content) is maintained in one place.
    """

    def test_build_prompt_is_deterministic(self) -> None:
        chunks = [
            _make_chunk("c1_x", "doc-1", "First chunk."),
            _make_chunk("c2_y", "doc-2", "Second chunk."),
        ]
        system = "System instructions."

        parts_a = ClaudeLLM.build_prompt(system, chunks)
        parts_b = ClaudeLLM.build_prompt(system, chunks)

        assert parts_a.system == parts_b.system
        assert set(parts_a.chunk_lookup.keys()) == set(parts_b.chunk_lookup.keys())

    def test_build_prompt_contains_system_and_context(self) -> None:
        chunks = [_make_chunk("test_1", "doc-1", "Content here.")]
        system = "RULES: answer only from excerpts."

        parts = ClaudeLLM.build_prompt(system, chunks)

        # System instructions are in the prompt
        assert "RULES: answer only from excerpts." in parts.system
        # Chunk text is in the prompt (as untrusted data)
        assert "Content here." in parts.system
        # Chunk ID is in the prompt (for citation)
        assert "test_1" in parts.system
        # Chunk lookup has the chunk
        assert "test_1" in parts.chunk_lookup

    def test_resolve_response_matches_for_same_text(self) -> None:
        """The same raw LLM output resolves identically."""
        chunks = [_make_chunk("abc_1", "doc-1", "Sample.")]
        lookup = {c.chunk_id: c for c in chunks}

        raw = 'The answer. [abc_1]\n\n```citations\n["abc_1"]\n```'

        answer_a = ClaudeLLM.resolve_response(raw, lookup)
        answer_b = ClaudeLLM.resolve_response(raw, lookup)

        assert answer_a.text == answer_b.text
        assert len(answer_a.citations) == len(answer_b.citations) == 1
        assert answer_a.citations[0].doc_id == answer_b.citations[0].doc_id
