"""Heuristic injection detector (T1/T2 detection layer).

Scans retrieved chunk text for known injection signatures and
neutralizes matched spans by replacing them with a placeholder.
This is DETECTION + SANITIZATION on top of structural PREVENTION
(the tool gate and untrusted-data wrapping).

Honest framing: detection is heuristic. Novel injections will evade
it. The structural gate holds regardless. Detection catches known
patterns; prevention catches everything else.

Span-level sanitization: only the matched text is replaced, not the
whole chunk. This bounds a false positive to a sentence rather than
silently removing a legitimate source. The source document is never
modified; only the prompt copy is sanitized.

Conversation history is also client-supplied and could carry injected
text. Out of scope this pass; the same structural controls apply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from custos.interfaces import Chunk

PLACEHOLDER = "[injected instruction removed]"

# Patterns tuned to the three seeded corpus payloads plus common
# injection variants. Each pattern captures the full sentence or
# block containing the injection attempt.

_PATTERNS: list[re.Pattern[str]] = [
    # Role impersonation: "SYSTEM:", "assistant:", "user:" and everything
    # that follows until a separator (---), blank line, or end of text
    re.compile(
        r"(?:^|\n)\s*(?:SYSTEM|assistant|user)\s*:[\s\S]*?(?=\n---|\n\n|\Z)",
        re.IGNORECASE,
    ),
    # Override phrasing: "ignore all/prior/previous/your instructions"
    re.compile(
        r"[^.]*ignore\s+(?:all\s+)?(?:prior|previous|your)\s+instructions[^.]*\.?",
        re.IGNORECASE,
    ),
    # Identity override: "you are now", "you are no longer", "you are DAN"
    re.compile(
        r"[^.]*you are (?:now|no longer|DAN)[^.]*\.?",
        re.IGNORECASE,
    ),
    # Admin/auth claim: "granted admin/temporary access", "authorized data audit/backup"
    re.compile(
        r"[^.]*(?:granted|authorized)\s+(?:admin|temporary)\s+(?:access|audit|backup)[^.]*\.?",
        re.IGNORECASE,
    ),
    # Label drop: attempts to remove "(simulated)" label
    re.compile(
        r"[^.]*(?:no longer|remove|dropped)[^.]*\(simulated\)[^.]*\.?",
        re.IGNORECASE,
    ),
    # Label drop: "actions are now live/real"
    re.compile(
        r"[^.]*actions are now (?:live|real)[^.]*\.?",
        re.IGNORECASE,
    ),
    # Hidden HTML comment instructions
    re.compile(
        r"<!--[\s\S]*?-->",
    ),
    # Prompt template markers
    re.compile(
        r"\[INST\][\s\S]*?\[/INST\]",
        re.IGNORECASE,
    ),
    # "user has pre-approved" social engineering
    re.compile(
        r"[^.]*(?:user has (?:pre-)?approved|this is (?:an )?authorized)[^.]*\.?",
        re.IGNORECASE,
    ),
]


@dataclass
class DetectionResult:
    """Result of scanning chunks for injection attempts."""

    detected: bool
    count: int  # number of matched spans across all chunks
    sanitized_chunks: list[Chunk]  # chunks with matched spans replaced


class InjectionDetector:
    """Heuristic injection detector with span-level sanitization.

    Scans chunk text for known injection patterns. Matched spans are
    replaced with a neutral placeholder in the prompt copy; the source
    document is never modified.
    """

    def __init__(self, patterns: list[re.Pattern[str]] | None = None) -> None:
        self._patterns = patterns if patterns is not None else _PATTERNS

    def scan(self, chunks: list[Chunk]) -> DetectionResult:
        """Scan chunks and return sanitized copies if injections found."""
        total_matches = 0
        sanitized: list[Chunk] = []

        for chunk in chunks:
            text = chunk.text
            match_count = 0

            for pattern in self._patterns:
                matches = list(pattern.finditer(text))
                if matches:
                    match_count += len(matches)
                    text = pattern.sub(PLACEHOLDER, text)

            total_matches += match_count
            if match_count > 0:
                # Create a new Chunk with sanitized text
                sanitized.append(Chunk(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    text=text,
                    section_path=chunk.section_path,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    permissions=chunk.permissions,
                    metadata=chunk.metadata,
                ))
            else:
                sanitized.append(chunk)

        return DetectionResult(
            detected=total_matches > 0,
            count=total_matches,
            sanitized_chunks=sanitized,
        )
