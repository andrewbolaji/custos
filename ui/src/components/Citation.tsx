import { useState } from "react";

import type { Citation as CitationType } from "../types";

interface CitationProps {
  citation: CitationType;
  index: number;
}

export function Citation({ citation, index }: CitationProps) {
  const [expanded, setExpanded] = useState(false);
  const sectionLabel = citation.section_path.join(" > ");

  return (
    <div className="citation">
      <button
        className="citation-toggle"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        <span className="citation-badge">{index + 1}</span>
        <span className="citation-label">{citation.doc_name}</span>
        <span className="citation-section">{sectionLabel}</span>
        <span className="citation-chevron">{expanded ? "\u25B2" : "\u25BC"}</span>
      </button>
      {expanded && (
        <div className="citation-snippet">
          <p>{citation.snippet}</p>
        </div>
      )}
    </div>
  );
}
