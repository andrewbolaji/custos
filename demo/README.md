# Demo kit

What this is: a proof-of-value kit for showing Custos to a prospective
buyer — a seeded 16-document corpus for a fictional company (Larkspur
Analytics) with three access personas, plus the security questionnaire
their team will ask for anyway.

How to start it: `make demo` (needs Docker running, `make install` already
run once, and `ANTHROPIC_API_KEY` exported — see the error messages if
something's missing). `make demo-down` tears it down; `make demo-reset`
does both back to back for a clean restart between sessions.

Where the script is: `DEMO_SCRIPT.md` — a 30-minute, read-it-almost-verbatim
walkthrough, plus a fallback plan for the five most likely live failures
and answers to the questions you'll actually get asked.

Where the questionnaire is: `../docs/SECURITY_QUESTIONNAIRE.md` — filled in
against the code, with a real "known limitations" section, not a green
checklist.

How long bring-up takes: `make demo-reset` (full teardown + fresh bring-up)
measured at **31.5 seconds** end-to-end (`docker compose down` → up →
indexed → API healthy → UI reachable), timed with `time make demo-reset` on
a warm cache (embedder model and Docker image already local). Real number,
not rounded down. First run on a machine with neither cached will take
longer (mostly a one-time BGE model download, a few tens of seconds); still
comfortably within the 3-minute budget.

Corpus detail, permissions table, and the seeded contradiction/injection/gap
live in `corpus/README.md`.
