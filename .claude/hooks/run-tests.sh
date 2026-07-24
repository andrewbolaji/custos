#!/usr/bin/env bash
# Stop hook — the "tests pass" gate.
#
# Runs this repo's real backend test command (make test → pytest, 199 tests)
# and BLOCKS Claude from finishing while it fails. Claude Code treats a Stop
# hook that exits 2 as a blocking error: stdout is ignored, stderr is fed back
# to the model, and the turn is not allowed to end. Exit 0 lets it stop.
#
# This is a hard gate on purpose (see CLAUDE.md "Definition of done"): it does
# NOT honor stop_hook_active to bail out early, because finishing with failing
# tests is exactly what it exists to prevent.
set -uo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$PROJECT_DIR" || { echo "Stop hook: cannot cd to $PROJECT_DIR" >&2; exit 2; }

LOG="$(mktemp)"
if make test >"$LOG" 2>&1; then
  rm -f "$LOG"
  exit 0
fi

{
  echo "BLOCKED: backend tests are failing — do not finish until they pass."
  echo "Command: make test   (cwd: $PROJECT_DIR)"
  echo "--- last 30 lines of output ---"
  tail -n 30 "$LOG"
} >&2
rm -f "$LOG"
exit 2
