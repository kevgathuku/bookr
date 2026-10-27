---
name: implement
description: "Implement a piece of work based on a spec or set of tickets."
disable-model-invocation: true
---

Implement the work described by the user in the spec or tickets.

If the user passes a ticket reference, fetch it from the issue tracker and state its title before starting. If the reference is ambiguous, ask.

Call the Skill tool with "tdd" where possible, at pre-agreed seams.
Where no Skill/subagent tool exists in the environment, run the
referenced skill inline (read its SKILL.md, follow its loop, report in
its format) and say so in one line.

Run typechecking regularly (if the repo configures it — if not, note
the absence once and move on; do not silently skip every time), single
test files regularly, and the full test suite once at the end.

## Python style: wemake-python-styleguide

All new Python code follows wemake (`uv run flake8 <touched files>` —
config in `.flake8`). Legacy files are out of scope: gate only the files
the ticket creates or modifies, never the whole repo. Six rules are off
repo-wide for Django-declarative collisions (`objects`, nested TextChoices,
field literals, `Q`/`F` imports — reasons in `.flake8`); tests get relaxed
naming/structure rules via `per-file-ignores`. Fix every other finding in
new code — the guide has repeatedly caught real issues (bloated services,
mutable constants, dead test locals). If a rule fights a framework-mandated
pattern, prefer a small documented ignore over contorting the code.

Once done, call the Skill tool with "code-review" to review the work.

Then always close out the ticket, every time, in this order:

1. Record: ingest every decision reached (rationale included) plus any new
   environment/verification facts into project memory.
2. Graph: rebuild the repo context graph so it reflects the changes.
3. Commit: commit the work to the current branch (never push unless asked).
4. Tracker: close the ticket so the next unblocked one opens up.

## Session discipline (prevents lost work)

- End every turn with the tree committed, or say plainly what is
  uncommitted and why. Never let done work sit uncommitted across an
  interruption: when a new instruction arrives mid-ticket, finish the
  current atomic step, commit the ticket's done files (message cites the
  ticket), then switch.
- If blocked on an approval, commit everything done first, then ask —
  the question must never hold the work hostage.
- Start each turn by stating the active ticket + gate status
  (tests/lint/wemake) in one line, so drift is visible immediately.
