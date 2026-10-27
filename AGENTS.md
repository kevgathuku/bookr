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
  Membership spanning/per-venue), `tests/` (pytest-django, factories in
  lesson 3), `docker/postgres/` + `docker-compose.yml` (db on host :5433).
- Quality gates: `uv run ruff check .`, `uv run ruff format --check .`,
  `DATABASE_URL=... uv run pytest tests/ -q` (+ CI in `.github/`).
- Conventions: explicit names with units (`class_late_cancel_hours`, not
  `_h`); `condition=` (Django 6.1, never `check=`); `ClassVar` on Meta
  constraint lists (RUF012); no code before its lesson.

## Project memory (mempal, wing `bookr`) — mandatory

A mempal store is initialized for this folder (wing `bookr`). It exists so
no agent ever re-discovers what a prior session already learned. These are
requirements, not suggestions:

- **Read before deciding.** Before taking any decision in an area you're
  about to work in, query memory first: `mempal_search` scoped to wing
  `bookr` (past decisions, rationale, bug history, why things are shaped
  as they are), or `mempal_brief` for a citation-first brief on the topic.
  If you haven't seen the memory protocol this session, call
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
