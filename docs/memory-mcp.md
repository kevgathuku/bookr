# Project memory via mempal (MCP-only in this environment)

All persistent project memory lives in mempal, wing `bookr`. It is the
only memory store — do not use `bd remember` (the Beads block's remember
line does not apply here; `bd` stays strictly for issue tracking).

## Connecting (once per session)

The tools are not direct functions here. They hang off the `mcp` gateway
under server `mempal`, which starts disconnected:

1. `mcp({ connect: "mempal" })` — connect (retry if it fails).
2. `mcp({ tool: "mempal_status", args: {} })` — required first call: confirms
   the wing list and returns the full memory protocol. Do not guess wing
   names before seeing them here; an unknown wing silently returns nothing.

After that, every memory op is `mcp({ tool: "<name>", args: {...} })`.

## The three ops you need

- **Recall**: `mempal_search` (`{query, wing: "bookr", ...}`) before any
  decision; `mempal_brief` for a citation-first brief; `mempal_context`
  for ordered dao/shu/qi guidance. No wing filter when unsure — global
  search beats zero results.
- **Record**: `mempal_ingest` (`{content, wing: "bookr"}` plus rationale,
  not just outcome; `importance` 0-5). Default writes are evidence
  drawers: content + wing only — knowledge-only fields
  (`statement`, `tier`, `status`, `*_refs`, ...) are rejected.
- **Never**: `bd remember`, `MEMORY.md`, or any other ad-hoc memory file.

## Why this doc exists

Without it, each session re-discovers the gateway + connect + wing
dance from scratch. If the access path changes (direct tools, new wing,
auth), update this file — not AGENTS.md.
