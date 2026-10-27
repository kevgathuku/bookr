---
name: loop
description: "Run a beads ticket queue in dependency order with minimal intervention: one ticket at a time from ready to closed, with gates and close-out every time."
---

# Ticket loop

Work the queue; don't admire it. One ticket at a time, in dependency order,
until nothing ready remains. Pause only for critical confirmations (a config
change the `wps` guardrail reserves for the user, a scope call that routes
work to another ticket/phase, a missing dependency). Everything else —
proceed.

## Order

- `bd ready` shows what's unblocked. Pick by dependency impact (the ticket
  that unblocks the longest chain first); backend before frontend, MVP (P1)
  before Phase 2 (P2).
- `bd update <id> --claim`, state its title, then deliver it THROUGH the
  `implement` skill (read its SKILL.md, follow its loop). That skill owns
  the delivery chain — tdd → typecheck/tests → wps → `code-review` →
  record/graph/commit/close — so review and close-out are never skipped.
  The gates below are the acceptance bar its work must meet. Next.
- Never start a ticket whose dependencies are open. Never batch tickets.

## Per ticket

Fixed order — never reorder, never skip: pre-conditions → TDD slices →
gates → review → fixes → re-gate → close-out. The ticket's final commit
happens only after review findings are fixed and gates are re-green.
(Interim commits of done slices are fine; the close-out commit is not.)

1. **Pre-conditions**: `graft build`; orient with `graft ask --source`
   (spans, not whole files); memory search scoped to the project wing —
   never re-derive rationale memory already holds. Prefer graft for ALL
   codebase exploration (`ask`/`skeleton`/`callers`/`grep`) over raw grep
   or reading whole files; open source only at exact spans graft returns.
2. **TDD**: pytest by default at pre-agreed seams, red first, one vertical
   slice per cycle. The full E2E gate runs only once its harness ticket
   lands; until then the ticket's pytest scope plus all prior scopes is
   the gate (record the substitution, don't silently narrow).
3. **Gates** (every ticket, no exceptions — run the commands, don't trust
   memory of an earlier green): ticket scope + full suite green;
   E2E scope for the ticket plus all previously-green scopes;
   `makemigrations --check` clean; `ruff check` + `ruff format --check`
   clean; `flake8` on touched files (wemake, `.flake8` scope); `mypy` clean
   where configured (if unconfigured, note it once and move on). Frontend
   tickets add: `tsc --noEmit`, `biome check .`, `vitest run`, production
   `build`, codegen `generate:api` with no drift. Backend tickets with API
   changes add: schema builds with errors 0.
4. **Review**: three axes (Standards, Spec, Necessity) reported separately.
   A summary is not a review: read the `ponytail-review` SKILL.md and run
   its pass on the ticket's diff, emitting its output format (What this
   change does / numbered findings / Verdict) before the close-out commit.
   Run referenced skills inline where no skill/subagent tool exists and say
   so. WPS findings go through the `wps` loop; config changes need user
   approval (pre-approved sets live in `.flake8`, documented inline).
   Standing rule: structural WPS findings whose fix would degrade intent
   (endpoint-file growth per ticket, linear E2E scripts) take the
   documented per-file-ignore without asking.
5. **Close-out, every time, in order**: ingest decisions + new facts into
   project memory (rationale included); `graft build`; commit to the
   current branch (message cites the ticket; never push unless asked);
   close the tracker issue so the next unblocks.

## Session discipline (prevents lost work)

- End every turn with the tree committed, or say plainly what is
  uncommitted and why.
- Interruption mid-ticket: finish the current atomic step, commit the
  ticket's done files, then switch. Blocked on an approval: commit
  everything done first, then ask — the question must never hold the
  work hostage.
- Start each turn stating active ticket + gate status in one line.

## Out of scope, always

- Environment/installer files (scaffolds, IDE dirs, skill drops, lockfiles
  owned by installers): never stage, never delete, never "fix".
- Legacy files are exempt from new gates; gate touched files only.
- Deferred behavior gets recorded with its owner ticket, not built early
  (no code before its ticket/phase). Missing owners become gap notes at
  close-out, not scope creep mid-ticket.
