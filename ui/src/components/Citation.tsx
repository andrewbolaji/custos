import { useState } from "react";

import type { Citation as CitationType } from "../types";

/**
 * Strip markdown syntax from a snippet for clean prose display.
 * Handles headings, bold, italic, bullets, links, and code fences.
 */
function stripMarkdown(text: string): string {
  return text
    .replace(/^#{1,6}\s+/gm, "")      // headings
    .replace(/\*\*(.+?)\*\*/g, "$1")   // bold
    .replace(/__(.+?)__/g, "$1")        // bold alt
    .replace(/\*(.+?)\*/g, "$1")       // italic
    .replace(/_(.+?)_/g, "$1")          // italic alt
    .replace(/`(.+?)`/g, "$1")          // inline code
    .replace(/^\s*[-*+]\s+/gm, "")     // unordered bullets
    .replace(/^\s*\d+\.\s+/gm, "")     // ordered bullets
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1") // links
    .replace(/```[\s\S]*?```/g, "")    // fenced code
    .replace(/\n+/g, " ")              // collapse newlines
    .trim();
}

interface CitationProps {
  citation: CitationType;
  index: number;
}

export function Citation({ citation, index }: CitationProps) {
  const [expanded, setExpanded] = useState(false);
  const sectionLabel = citation.section_path.join(" \u203A ");
  const cleanSnippet = stripMarkdown(citation.snippet);

  return (
    <div>
      <button
        className="src-chip"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        <span className="src-num">{index + 1}</span>
        <div>
          <div className="src-doc">{citation.doc_name}</div>
          <div className="src-path">{sectionLabel}</div>
        </div>
      </button>
      {expanded && (
        <div className="src-snippet">
          <p>{cleanSnippet}</p>
        </div>
      )}
    </div>
  );
}
