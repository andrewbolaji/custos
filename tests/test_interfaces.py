"""Tests for the interface contracts.

Verifies that the ABCs are properly defined and that data objects work as
expected. These are structural tests, not behavioral (behavior ships with
implementations in Phase 1+).
"""

from __future__ import annotations

from custos.interfaces import (
    LLM,
    Answer,
    Chunk,
    Citation,
    Embedder,
    Guardrail,
    GuardrailResult,
    Retriever,
    Tool,
    ToolCall,
    ToolResult,
    VectorStore,
)


class TestDataObjects:
    """Frozen dataclasses must be immutable and constructable."""

    def test_chunk_is_frozen(self) -> None:
        c = Chunk(
            chunk_id="c1",
            doc_id="d1",
            text="hello",
            section_path=["A", "B"],
            char_start=0,
            char_end=5,
            permissions=["general"],
        )
        assert c.chunk_id == "c1"
        try:
            c.chunk_id = "c2"  # type: ignore[misc]
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass

    def test_citation_fields(self) -> None:
        cit = Citation(
            doc_id="d1",
            doc_name="Test Doc",
            section_path=["A"],
            char_start=0,
            char_end=10,
            snippet="hello test",
        )
        assert cit.doc_name == "Test Doc"
        assert cit.snippet == "hello test"

    def test_answer_defaults(self) -> None:
        a = Answer(text="I don't know.", citations=[], refused=True)
        assert a.refused is True
        assert len(a.citations) == 0

    def test_guardrail_result(self) -> None:
        r = GuardrailResult(passed=False, reason="injection detected")
        assert not r.passed

    def test_tool_call_and_result(self) -> None:
        tc = ToolCall(tool_name="lookup", arguments={"id": "123"}, side_effectful=False)
        assert not tc.side_effectful
        tr = ToolResult(tool_name="lookup", output={"found": True}, simulated=True)
        assert tr.simulated is True


class TestABCsAreAbstract:
    """Each ABC must not be directly instantiable."""

    def test_embedder_is_abstract(self) -> None:
        try:
            Embedder()  # type: ignore[abstract]
            raise AssertionError("Should not instantiate ABC")
        except TypeError:
            pass

    def test_vector_store_is_abstract(self) -> None:
        try:
            VectorStore()  # type: ignore[abstract]
            raise AssertionError("Should not instantiate ABC")
        except TypeError:
            pass

    def test_retriever_is_abstract(self) -> None:
        try:
            Retriever()  # type: ignore[abstract]
            raise AssertionError("Should not instantiate ABC")
        except TypeError:
            pass

    def test_llm_is_abstract(self) -> None:
        try:
            LLM()  # type: ignore[abstract]
            raise AssertionError("Should not instantiate ABC")
        except TypeError:
            pass

    def test_guardrail_is_abstract(self) -> None:
        try:
            Guardrail()  # type: ignore[abstract]
            raise AssertionError("Should not instantiate ABC")
        except TypeError:
            pass

    def test_tool_is_abstract(self) -> None:
        try:
            Tool()  # type: ignore[abstract]
            raise AssertionError("Should not instantiate ABC")
        except TypeError:
            pass
