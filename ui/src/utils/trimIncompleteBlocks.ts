/**
 * Trim trailing incomplete block-level markdown structures from
 * streaming text before handing it to react-markdown.
 *
 * Prevents the "flash" where partial tables render as literal pipes
 * and partial code blocks render as unclosed prose, then snap into
 * their final structure when complete.
 *
 * DOES NOT key on bare ``` -- that truncated legitimate code blocks
 * in a past bug. Tracks full fence openers and their closure.
 */

/**
 * Returns the text with any trailing incomplete block removed.
 * "Incomplete" means:
 * - A trailing run of table rows (lines starting with |) not yet
 *   followed by a blank line or non-table line.
 * - An unclosed fenced code block (opened with ```lang but no
 *   matching closing ```).
 */
export function trimIncompleteBlocks(text: string): string {
  let result = text;

  // 1. Trim trailing incomplete table.
  // A table block is a run of lines starting with | at the end of
  // the text, not yet terminated by a blank line. If we see pipe
  // lines at the tail without a complete table (header + separator
  // + at least one data row + termination), withhold them.
  const lines = result.split("\n");
  let tableStart = -1;
  for (let i = lines.length - 1; i >= 0; i--) {
    const trimmed = lines[i].trim();
    if (trimmed.startsWith("|")) {
      tableStart = i;
    } else if (trimmed === "") {
      // blank line before the pipe run -- the table block starts after this
      break;
    } else {
      // non-pipe, non-blank line -- not part of a table
      break;
    }
  }

  if (tableStart >= 0) {
    // Check if the table is complete: needs header, separator (with dashes),
    // and must end with a blank line or end-of-text after the last row.
    const tableLines = lines.slice(tableStart);
    const hasSeparator = tableLines.some((l) =>
      /^\|[\s:|-]+\|/.test(l.trim()) && l.includes("---"),
    );
    const lastLine = lines[lines.length - 1].trim();
    const terminated = lastLine === "" || !lastLine.startsWith("|");

    if (!hasSeparator || !terminated) {
      // Incomplete table -- withhold
      result = lines.slice(0, tableStart).join("\n");
    }
  }

  // 2. Trim trailing unclosed fenced code block.
  // Find the last opening fence (```something) and check if it has
  // a matching closing fence after it.
  const fenceOpenRe = /^(`{3,})(\w*)\s*$/gm;
  let lastOpenPos = -1;
  let lastOpenFence = "";
  let match;
  while ((match = fenceOpenRe.exec(result)) !== null) {
    lastOpenFence = match[1]; // the backtick sequence
    lastOpenPos = match.index;
  }

  if (lastOpenPos >= 0) {
    // Look for a closing fence after the opener
    const afterOpen = result.slice(lastOpenPos + lastOpenFence.length);
    const closeRe = new RegExp(`^${lastOpenFence}\\s*$`, "m");
    // The first match of closeRe in afterOpen is the opener's own line,
    // so we need to skip past it
    const afterFirstLine = afterOpen.indexOf("\n");
    if (afterFirstLine >= 0) {
      const rest = afterOpen.slice(afterFirstLine + 1);
      if (!closeRe.test(rest)) {
        // Unclosed -- withhold the entire code block
        result = result.slice(0, lastOpenPos);
      }
    } else {
      // Only the opening line, no content yet -- withhold
      result = result.slice(0, lastOpenPos);
    }
  }

  return result.trimEnd();
}
