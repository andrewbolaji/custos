"""Tests for the structural Markdown chunker.

Verifies heading-aware splitting, char-offset correctness, oversized section
fallback, section_path hierarchy, and empty/edge cases.
"""

from __future__ import annotations

from custos.chunker import chunk_document


class TestStructuralSplitting:
    """Chunks must follow heading boundaries."""

    def test_splits_on_headings(self) -> None:
        text = (
            "# Title\n\nIntro text.\n\n## Section A\n\n"
            "Content A.\n\n## Section B\n\nContent B.\n"
        )
        chunks = chunk_document(text, doc_id="test", permissions=["general"])
        # Should produce at least 2 chunks (Section A and Section B)
        assert len(chunks) >= 2
        section_titles = [c.section_path[-1] for c in chunks]
        assert "Section A" in section_titles
        assert "Section B" in section_titles

    def test_nested_headings_produce_path(self) -> None:
        text = "# Top\n\nTop text.\n\n## Mid\n\nMid text.\n\n### Deep\n\nDeep text.\n"
        chunks = chunk_document(text, doc_id="test", permissions=["general"])
        deep_chunks = [c for c in chunks if "Deep" in c.section_path]
        assert len(deep_chunks) == 1
        assert deep_chunks[0].section_path == ["Top", "Mid", "Deep"]

    def test_preamble_before_first_heading(self) -> None:
        text = "Some preamble text.\n\n# First Heading\n\nBody.\n"
        chunks = chunk_document(text, doc_id="test", permissions=["general"])
        preamble_chunks = [c for c in chunks if "(preamble)" in c.section_path]
        assert len(preamble_chunks) == 1

    def test_plain_text_no_headings(self) -> None:
        text = "Just plain text with no headings at all.\n\nAnother paragraph.\n"
        chunks = chunk_document(text, doc_id="test", permissions=["general"])
        assert len(chunks) >= 1
        assert "(untitled)" in chunks[0].section_path


class TestCharOffsets:
    """Every chunk's char offsets must resolve to its text in the original."""

    def test_offsets_match_text(self) -> None:
        text = "# A\n\nAlpha content.\n\n# B\n\nBravo content.\n"
        chunks = chunk_document(text, doc_id="test", permissions=["general"])
        for chunk in chunks:
            actual = text[chunk.char_start : chunk.char_end]
            assert actual == chunk.text, (
                f"Offset mismatch: text[{chunk.char_start}:{chunk.char_end}] "
                f"= {actual!r}, chunk.text = {chunk.text!r}"
            )

    def test_offsets_on_large_document(self) -> None:
        """Test on the real employee handbook from the demo corpus."""
        from pathlib import Path

        corpus_dir = Path(__file__).parent.parent / "corpus" / "output"
        handbook = corpus_dir / "handbook-001.md"
        if not handbook.exists():
            import subprocess
            import sys

            subprocess.check_call(  # noqa: S603
                [sys.executable, str(Path(__file__).parent.parent / "corpus" / "generate.py")]
            )

        text = handbook.read_text()
        chunks = chunk_document(text, doc_id="handbook-001", permissions=["general"])
        assert len(chunks) > 0
        for chunk in chunks:
            actual = text[chunk.char_start : chunk.char_end]
            assert actual == chunk.text


class TestOversizedFallback:
    """Sections exceeding MAX_CHUNK_CHARS are split on paragraph boundaries."""

    def test_oversized_section_splits(self) -> None:
        # Create a section with >100 chars (using a small max for testing)
        text = "# Big Section\n\n" + "A" * 60 + "\n\n" + "B" * 60 + "\n"
        chunks = chunk_document(
            text, doc_id="test", permissions=["general"], max_chunk_chars=80
        )
        assert len(chunks) >= 2
        # All chunks should share the same section path
        for chunk in chunks:
            assert "Big Section" in chunk.section_path

    def test_offsets_correct_after_split(self) -> None:
        text = "# S\n\n" + "Word " * 400 + "\n\n" + "More " * 400 + "\n"
        chunks = chunk_document(
            text, doc_id="test", permissions=["general"], max_chunk_chars=500
        )
        for chunk in chunks:
            actual = text[chunk.char_start : chunk.char_end]
            assert actual == chunk.text


class TestPermissionsPassthrough:
    """Chunks carry the document's permissions."""

    def test_permissions_set(self) -> None:
        text = "# Test\n\nContent.\n"
        chunks = chunk_document(text, doc_id="test", permissions=["hr"])
        for chunk in chunks:
            assert chunk.permissions == ["hr"]

    def test_multiple_permissions(self) -> None:
        text = "# Test\n\nContent.\n"
        chunks = chunk_document(text, doc_id="test", permissions=["finance", "owner"])
        for chunk in chunks:
            assert chunk.permissions == ["finance", "owner"]
