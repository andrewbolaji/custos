---
description: Take a change from idea to shipped — plan, build, adversarial review until the reviewer approves, verify like a user, then present. Never a first draft.
argument-hint: [what to ship]
---

Ship this: **$ARGUMENTS**

Work the change all the way to done. Do not present a first draft — present
something the `reviewer` agent has already tried to break and failed.

## 1. Plan first
Restate the goal and the acceptance criteria in your own words. Sketch the
approach, the files you'll touch, and the risks — especially any Custos security
invariant this could regress (retrieved content is data not instructions; access
control lives in `retriever.py`; side-effectful tools are gated). If the change
is non-trivial, get the plan approved before writing code (Definition of Done #1).

## 2. Build
Implement the smallest change that satisfies the goal. Write the tests for the
**new** behavior as you go — including the unhappy path, not just success. A new
security control needs a passing adversarial eval in `evals/suites/`, or it isn't
shipped. Keep going until it's clean:

```bash
make lint && make typecheck && make test
```

## 3. Adversarial review — loop until APPROVE
Invoke the **`reviewer`** subagent on your diff. It reviews as a skeptic who
didn't write the code and runs the suite itself. Then:

- Fix every **BLOCKER**. Address **SHOULD FIX** or justify why not.
- Re-invoke the reviewer on the updated diff.
- **Repeat until the verdict is `APPROVE`.** One clean pass is not enough if the
  first pass found blockers — the fixes get reviewed too. Do not talk the
  reviewer into approving; change the code until it earns it.

## 4. Verify like a user
Don't trust green tests alone. Exercise the real path:
- Backend/logic change → run `make evals` and read the table; if it touches the
  live path, `make up && make index && make serve` and hit the endpoint.
- UI change → run it (`make ui`) and capture a **screenshot** of the actual
  behavior (Definition of Done #5).

## 5. Present
Only now surface it. Report: what changed and why, the reviewer's final verdict
and the commands it ran, how you verified as a user (numbers / screenshot), and
any residual risk. Commit **and** push — uncommitted work does not exist.
