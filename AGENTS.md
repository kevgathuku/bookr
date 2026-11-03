<!-- graft:start -->
## Graft — repo context graph

This repo is indexed in `graft/`: small linked markdown nodes that explain each
system and carry exact file:line spans, kept in sync with the code through git.

For ANY task here — understanding how something works, finding where code lives,
or scoping a change — get context from the graph before grepping or opening
source files. Re-ask freely (it's cheap) and reuse literal identifiers you
already have (symbol, error string, file name) as the query. New to this repo?
Run `graft map` first — a token-budgeted orientation (dir clusters, hubs,
hotspots), no LLM, no key.

- Run `graft ask "<your question>" --source` → ranked nodes with the relevant
  code spans inlined (each hit's ≤8-line crux by default; `--full` for whole
  definitions when the crux isn't enough). Match the tool to the task shape:
  for understanding or editing, the top node IS the answer — cite its
  `covers:` file:line spans and edit straight from `--source`. For
  exhaustive tasks ("every occurrence / every caller of this pattern"), ranked
  results are top-N, not complete — run `graft grep "<literal>"` instead
  (exhaustive over indexed files, grouped by enclosing symbol), falling back
  to raw `grep -rn` only for unindexed files.
- `graft skeleton <file>` → every definition's signature + span, ~10× cheaper
  than reading the file; use it to skim an API surface.
- `graft callers <symbol>` gives precomputed, exact edges — who calls this.
  Add `--direction out` for what it calls, or `--depth N` to walk
  transitively for the full blast radius. For structural questions, skip
  ranking and use this directly.
- Or browse: `graft/INDEX.md` lists every node; follow the links.
- Monorepos and folders of multiple repos rank fairly across sub-projects —
  hits carry `[scope/]` labels naming which one they're from. Narrow with
  `graft ask "<task>" --in <scope>/` once you know where you're working.

If a returned span is truncated ("+N more lines"), open the file at that exact
range before finalizing. Only open source files when a node genuinely lacks a
needed detail, and then at the exact file:line the node points to — never
re-read whole files.

After big code changes, refresh the graph with `graft build` (deterministic,
no API key, $0).
<!-- graft:end -->

## Project structure

- Contracts: `SPEC.md` (backend), `SPEC-frontend.md` (React+TS SPA),
  `.scratch/bookr-platform/spec.md` (ticket copy). (Human learning track —
  `TUTORIAL.md`, `lessons/` — intentionally omitted here; agents build
  from the contracts, not the tutorials.)
- Code: `config/` (project, settings package `base/dev/prod`, strict env),
  `organizations/` (tenancy: Organization → Venue → VenuePolicy versions +
  Membership spanning/per-venue), per-app unit tests in `<app>/tests/` with
  shared factories + cross-app journeys in `tests/`, `docker/postgres/` +
  `docker-compose.yml` (db on host :5433).
- Quality gates: `uv run ruff check .`, `uv run ruff format --check .`,
  `DATABASE_URL=... SECRET_KEY=... uv run mypy .`,
  `uv run flake8 <touched files>` (wemake, config in `.flake8`),
  `uv run pytest -q` (+ CI in `.github/`). Parallel unit run (live-server
  smoke/e2e stay serial): `uv run pytest -q -n auto -m "not e2e and not smoke"`.
  Test DBs are reused: after editing an already-applied migration, rebuild
  once with `--create-db` or constraint changes silently won't apply.
- Conventions: explicit names with units (`class_late_cancel_hours`, not
  `_h`); `condition=` (Django 6.1, never `check=`); `ClassVar` on Meta
  constraint lists (RUF012); no code before its lesson.
- CHECK constraints: NULL satisfies a check, so nullable columns need
  explicit `isnull` conjuncts (`Q(plan=..., field__isnull=False, field__gt=0)`).
- Tests build rows via `tests/factories.py` (bare factory for boilerplate,
  explicit kwargs where the field is the assertion subject); direct
  `objects.create` only with a why-comment (uniqueness tests, `get_or_create`
  traps).

## Project memory (mempal, wing `bookr`) — mandatory

Access path: `docs/memory-mcp.md` (MCP gateway + connect dance — read it
first; it exists so no session re-discovers the store setup).

A mempal store is initialized for this folder (wing `bookr`). It exists so
no agent ever re-discovers what a prior session already learned. These are
requirements, not suggestions:

- **Read before deciding.** Before taking any decision in an area you're
  about to work in, query memory first: `mempal_search` scoped to wing
  `bookr` (past decisions, rationale, bug history, why things are shaped
  as they are), or `mempal_brief` for a citation-first brief on the topic.
  Cap `top_k` at 3-5 — the wing holds tens of thousands of drawers and
  uncapped searches dump noise. If you haven't seen the memory protocol
  this session, call
  `mempal_status` once first. Never reason from files alone when memory
  may hold the rationale — the files show what, memory shows why.
- **Record every decision.** When a decision is reached — naming, model
  shape, constraint choice, tooling call, rejected alternative — persist it
  with `mempal_ingest` (wing `bookr` is required; include the rationale,
  not just the outcome). Default writes are evidence drawers: content +
  wing only; use `dry_run=true` to preview first.
- **Record new information discovered.** Bug causes, environment quirks
  (ports, versions, machine-specific behavior), corrected assumptions,
  verification results — if a future agent would benefit, ingest it.
- **Cite, don't duplicate.** Memory results carry `drawer_id`/`source_file`
  citations; reference them instead of re-recording the same fact.
- **`bd memories` is retired.** The 27 legacy keys were removed (content
  already lives in mempal); do not create new keys — mempal is the store.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:46cd31e7 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->
## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale. Codex 0.129.0+ can load Beads context automatically through native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.
<!-- END BEADS CODEX SETUP -->

## Reuse before creating (merged from workspace template)

Before writing new code, check the codebase first (graft ask/grep, then
raw grep): if something exists that's ~80% of the need, extend it; if
about to copy-paste, extract to a shared module instead. Prefer the
smallest complete change (see ponytail rules in the session prompt).

## File size (merged from workspace template)

One module = one concern; split on unrelated exports or when a file
stops being skimmable. (Within Django apps this composes with app-by-
feature layout; wemake WPS202 already caps module members for new code.)

## Verify functionality (merged from workspace template)

If it isn't tested, it doesn't work: unit scope per ticket, all prior
scopes stay green, lint gates (`ruff`, plus `flake8` on touched files
per the implement skill), and the E2E gate once the harness lands.
