"""Abstract interfaces for Custos's pluggable components.

Each interface is a contract. No retrieval, generation, or guardrail code imports
a concrete implementation directly. Swapping a provider is a config change, not a
rewrite. This is also what makes the eval suite possible: you can test the retriever
and guardrails in isolation with test doubles.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Data objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    """A retrievable unit of text with provenance metadata."""

    chunk_id: str
    doc_id: str
    text: str
    section_path: list[str]
    char_start: int
    char_end: int
    permissions: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Citation:
    """A resolved citation pointing to a real span in a source document."""

    doc_id: str
    doc_name: str
    section_path: list[str]
    char_start: int
    char_end: int
    snippet: str


@dataclass(frozen=True)
class Answer:
    """A grounded answer with citations."""

    text: str
    citations: list[Citation]
    refused: bool = False


@dataclass(frozen=True)
class GuardrailResult:
    """Outcome of a guardrail check."""

    passed: bool
    reason: str = ""
    redacted_text: str | None = None


@dataclass(frozen=True)
class ToolCall:
    """A request to invoke a tool."""

    tool_name: str
    arguments: dict[str, Any]
    side_effectful: bool


@dataclass(frozen=True)
class ToolResult:
    """The outcome of a tool invocation."""

    tool_name: str
    output: Any
    simulated: bool = False


# ---------------------------------------------------------------------------
# Interfaces
# ---------------------------------------------------------------------------


class Embedder(ABC):
    """Embed text into vectors. Provider is swappable via config."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""


class VectorStore(ABC):
    """Store and query vectors with payload filtering."""

    @abstractmethod
    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Insert or update chunks with their vectors."""

    @abstractmethod
    def query(
        self,
        vector: list[float],
        k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """Return the top-k closest chunks, filtered by payload conditions."""

    @abstractmethod
    def delete(self, chunk_ids: list[str]) -> None:
        """Remove chunks by ID."""


class Retriever(ABC):
    """Retrieve relevant chunks for a query, scoped to the requesting user.

    Access control (T5) lives here: the retriever filters by the user's
    document permissions at query time, not in the prompt.
    """

    @abstractmethod
    def retrieve(self, query: str, user_permissions: list[str], k: int = 5) -> list[Chunk]:
        """Return chunks the user is permitted to see, ranked by relevance."""


class LLM(ABC):
    """Generate a grounded answer from retrieved context."""

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        context_chunks: list[Chunk],
        user_query: str,
    ) -> Answer:
        """Return an answer with citations. Refuse if context does not support an answer."""


class Redactor(ABC):
    """Detect and mask PII in text. Provider is swappable via config."""

    @abstractmethod
    def redact(self, text: str) -> str:
        """Return text with PII replaced by typed placeholders."""


class Guardrail(ABC):
    """Check inputs, outputs, or actions against security policy."""

    @abstractmethod
    def check_input(self, text: str) -> GuardrailResult:
        """Screen user input for injection attempts or PII."""

    @abstractmethod
    def check_output(self, text: str) -> GuardrailResult:
        """Screen model output for PII leakage or exfiltration attempts."""

    @abstractmethod
    def gate_action(self, tool_call: ToolCall) -> GuardrailResult:
        """Decide whether a tool call should proceed, ask for confirmation, or be blocked."""


class Tool(ABC):
    """A tool the agent can invoke."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool name."""

    @property
    @abstractmethod
    def description(self) -> str:
        """What this tool does, for the LLM's tool-selection prompt."""

    @property
    @abstractmethod
    def side_effectful(self) -> bool:
        """True if invoking this tool changes state or sends data externally."""

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for the tool's input arguments."""

    @abstractmethod
    def run(self, arguments: dict[str, Any]) -> ToolResult:
        """Execute the tool and return the result."""
