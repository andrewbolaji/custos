"""Structural Markdown chunker with char-offset citation spans.

Splits documents on heading boundaries, preserving the section hierarchy.
Each chunk carries exact char offsets so citations can be resolved to the
original text. Oversized sections are split on paragraph boundaries.

Per ADR-004: no naive fixed-size splitting. Citations must resolve exactly.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from custos.interfaces import Chunk

MAX_CHUNK_CHARS = 1500

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass
class _Section:
    """Internal node in the section tree."""

    title: str
    level: int
    text: str
    char_start: int
    char_end: int
    path: list[str] = field(default_factory=list)


def _build_sections(text: str) -> list[_Section]:
    """Split Markdown text into sections by heading."""
    headings = list(_HEADING_RE.finditer(text))

    if not headings:
        return [
            _Section(
                title="(untitled)",
                level=0,
                text=text,
                char_start=0,
                char_end=len(text),
                path=["(untitled)"],
            )
        ]

    sections: list[_Section] = []

    # Content before the first heading (preamble)
    if headings[0].start() > 0:
        preamble = text[: headings[0].start()]
        if preamble.strip():
            sections.append(
                _Section(
                    title="(preamble)",
                    level=0,
                    text=preamble,
                    char_start=0,
                    char_end=headings[0].start(),
                    path=["(preamble)"],
                )
            )

    # Build a path stack for heading hierarchy
    path_stack: list[tuple[int, str]] = []

    for i, match in enumerate(headings):
        level = len(match.group(1))
        title = match.group(2).strip()

        # Pop stack to the parent level
        while path_stack and path_stack[-1][0] >= level:
            path_stack.pop()
        path_stack.append((level, title))

        section_start = match.start()
        section_end = headings[i + 1].start() if i + 1 < len(headings) else len(text)

        section_text = text[section_start:section_end]
        section_path = [t for _, t in path_stack]

        sections.append(
            _Section(
                title=title,
                level=level,
                text=section_text,
                char_start=section_start,
                char_end=section_end,
                path=section_path,
            )
        )

    return sections


def _split_oversized(section: _Section, max_chars: int) -> list[_Section]:
    """Split an oversized section on paragraph boundaries."""
    if len(section.text) <= max_chars:
        return [section]

    paragraphs = re.split(r"\n\n+", section.text)
    sub_sections: list[_Section] = []
    current_text = ""
    current_offset = section.char_start

    for para in paragraphs:
        candidate = (current_text + "\n\n" + para).strip() if current_text else para

        if len(candidate) > max_chars and current_text:
            # Flush current buffer
            sub_sections.append(
                _Section(
                    title=section.title,
                    level=section.level,
                    text=current_text,
                    char_start=current_offset,
                    char_end=current_offset + len(current_text),
                    path=list(section.path),
                )
            )
            current_offset = current_offset + len(current_text)
            # Skip whitespace between paragraphs
            remaining = section.text[current_offset - section.char_start :]
            ws_match = re.match(r"\s*", remaining)
            if ws_match:
                current_offset += ws_match.end()
            current_text = para
        else:
            current_text = candidate

    if current_text.strip():
        sub_sections.append(
            _Section(
                title=section.title,
                level=section.level,
                text=current_text,
                char_start=current_offset,
                char_end=current_offset + len(current_text),
                path=list(section.path),
            )
        )

    # If splitting produced nothing useful, return the original
    return sub_sections if sub_sections else [section]


def chunk_document(
    text: str,
    doc_id: str,
    permissions: list[str],
    max_chunk_chars: int = MAX_CHUNK_CHARS,
    metadata: dict[str, str] | None = None,
) -> list[Chunk]:
    """Chunk a Markdown document into retrievable units with citation spans.

    Each chunk's char_start and char_end are verified against the original text:
    text[chunk.char_start:chunk.char_end] equals chunk.text.

    Args:
        text: The full document text.
        doc_id: Unique document identifier.
        permissions: Access control tags (e.g., ["general"], ["hr"]).
        max_chunk_chars: Maximum characters per chunk before paragraph splitting.
        metadata: Optional extra metadata to attach to each chunk.

    Returns:
        List of Chunk objects with verified char offsets.
    """
    sections = _build_sections(text)

    # Split oversized sections
    split_sections: list[_Section] = []
    for section in sections:
        split_sections.extend(_split_oversized(section, max_chunk_chars))

    # Filter out empty/whitespace-only sections
    split_sections = [s for s in split_sections if s.text.strip()]

    chunks: list[Chunk] = []
    extra = metadata or {}

    for section in split_sections:
        chunk_id = f"{doc_id}_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{doc_id}:{section.char_start}')}"

        chunk = Chunk(
            chunk_id=chunk_id,
            doc_id=doc_id,
            text=section.text,
            section_path=section.path,
            char_start=section.char_start,
            char_end=section.char_end,
            permissions=permissions,
            metadata=extra,
        )

        # Verify offset correctness: the slice must equal the chunk text
        actual = text[chunk.char_start : chunk.char_end]
        if actual != chunk.text:
            msg = (
                f"Offset verification failed for chunk {chunk_id}: "
                f"text[{chunk.char_start}:{chunk.char_end}] does not match chunk text. "
                f"Expected {len(chunk.text)} chars, got {len(actual)}."
            )
            raise ValueError(msg)

        chunks.append(chunk)

    return chunks
