---
name: implement
description: "Implement a piece of work based on a spec or set of tickets."
disable-model-invocation: true
---

Implement the work described by the user in the spec or tickets.

If the user passes a ticket reference, fetch it from the issue tracker and state its title before starting. If the reference is ambiguous, ask.

Explore the codebase with graft first (`ask --source`, `skeleton`, `callers`, `grep`) — prefer it over raw grep or reading whole files; open source only at exact spans graft returns.

Call the Skill tool with "tdd" where possible, at pre-agreed seams.
The tdd skill lives at `.agents/skills/tdd/`.
Where no Skill/subagent tool exists in the environment, run the
referenced skill inline (read its SKILL.md, follow its loop, report in
its format) and say so in one line.

Run typechecking regularly, single test files regularly, and the full test suite once at the end.

## Frontend gates

Any turn touching `frontend/` runs all three before committing:

- `pnpm --dir frontend run lint`
- `pnpm --dir frontend run build` (`tsc -b && vite build`)
- `pnpm --dir frontend run test` (vitest run)

## Python style: wemake-python-styleguide

- `uv run flake8 <touched files>` (config in `.flake8`). Gate only files the ticket creates or modifies.
- Six repo-wide ignores for Django-declarative collisions; tests get relaxed rules via `per-file-ignores`. Fix every other finding.
- If a rule fights a framework-mandated pattern, prefer a small documented ignore over contorting the code.
- Before committing: `uv run ruff check .` repo-wide (CI fails on this).

Once done, call the Skill tool with "code-review" to review the work.
The code-review skill lives at `.agents/skills/code-review/` — read its
SKILL.md when running the review inline.

Then always close out the ticket, every time, in this order:

1. Record: ingest every decision reached (rationale included) plus any new
   environment/verification facts into project memory.
2. Graph: rebuild the repo context graph so it reflects the changes.
3. Commit: commit the work to the current branch (never push unless asked).
4. Tracker: close the ticket so the next unblocked one opens up.

## Session discipline (prevents lost work)

- End every turn with the tree committed, or say plainly what is
  uncommitted and why.
- When a new instruction arrives mid-ticket, finish the current atomic
  step, commit the ticket's done files (message cites the ticket), then
  switch.
- If blocked on an approval, commit everything done first, then ask.
- Start each turn by stating the active ticket + gate status
  (tests/lint/wemake) in one line.
