---
name: implement
description: "Implement a piece of work based on a spec or set of tickets."
disable-model-invocation: true
---

Implement the work described by the user in the spec or tickets.

If the user passes a ticket reference, fetch it from the issue tracker and state its title before starting. If the reference is ambiguous, ask.

Call the Skill tool with "tdd" where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite once at the end.

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
