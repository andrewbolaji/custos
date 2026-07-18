import { useState } from "react";

import type { Citation as CitationType } from "../types";

interface CitationProps {
  citation: CitationType;
  index: number;
}

export function Citation({ citation, index }: CitationProps) {
  const [expanded, setExpanded] = useState(false);
  const sectionLabel = citation.section_path.join(" \u203A ");

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
          <p>{citation.snippet}</p>
        </div>
      )}
    </div>
  );
}
