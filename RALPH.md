# RALPH.md — Ralph loop for bookr (Python mapping)

Ralph ([reference](https://ralphloop.sh/reference/)) is a bash loop that runs
a coding-agent CLI inside a deterministically-named Docker sandbox, verifies
with a project command, and repeats. The loop is language-agnostic; only the
verify toolchain in the reference is JS (Vitest/npm). This repo maps it to:

- Unit: `DATABASE_URL=postgres://bookr:bookr@localhost:5433/bookr uv run pytest tests/ -q`
- Lint: `uv run ruff check .`, `uv run ruff format --check .`, `uv run flake8 <touched files>`
- E2E: deferred to ticket `bookr-om5` (no harness yet); per-ticket pytest
  scope is the substitute until then. Playwright has first-class Python
  support — use it when the frontend lands, not the TS config.
- Tasks: `bd` (beads) is the tracker, not `.agent/tasks.json` (empty here).
  One Ralph iteration = highest-priority ready bead, claimed → implemented
  (implement skill) → gates → commit → `bd close`.

## Sandbox naming (per-agent + per-project)

`./ralph.sh --print-name` derives the name from agent + project dir, so each
agent CLI gets its own sandbox per project. At startup `./ralph.sh --login`
authenticates inside the correct named sandbox; during cleanup stop that
sandbox (`sbx stop $(./ralph.sh --print-name)` or `./ralph.sh` cleanup).
Switching `--agent` creates/reuses that agent's own sandbox — sandboxes
never share state across agents or projects.

Supported CLIs per the reference: `claude`, `codex`, `copilot`, `cursor`,
`gemini`, `opencode` (pass through after `--`, e.g.
`./ralph.sh --agent codex -- --model gpt-5.3-codex`).
