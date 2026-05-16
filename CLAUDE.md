# CLAUDE.md

Behavioral guidelines for agents working on this repo. Supersedes the generic
`C:\Code\CLAUDE.md` while loaded. Read on every session.

**Tradeoff:** these rules bias toward caution over speed. For trivial tasks, use judgment.

**Required reading on session start:**
1. [`AGENTS.md`](AGENTS.md) — your role + the registry of who owns what
2. [`docs/ORCHESTRATION.md`](docs/ORCHESTRATION.md) — system plan, domains, critical path
3. [`docs/WORKFLOW.md`](docs/WORKFLOW.md) — git policy: branch, commit, never auto-merge master
4. `docs/<your-agent>.md` if one exists (schema contract, etc.)

This file holds the cross-cutting *behavioral* rules every agent inherits, regardless of domain.

---

## 1. Think Before Coding

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.

**Read before you write.** Read `schema.sql` and your domain's existing parsers, plus adjacent domains' tables you'll join against. If you can't explain why existing code is structured the way it is, ask before changing it.

## 2. Match Caution to Reversibility

**Two-way doors — move fast:**
- Adding a parser, a chart, a column to an existing table you own.
- Refactoring inside your owned paths.
- Tweaking a query or a UI layout.

**One-way doors — slow down, surface, confirm:**
- Schema changes (`schema.sql`) — owned by the **schema** agent. If you're not schema, propose via `docs/CROSS_AGENT_NOTES.md`.
- Anything that ships data to a cloud LLM, especially raw rsids/genotypes (forbidden — derived traits only).
- Anything touching `private/` (minor's data) or moving files in/out of `w_data/`.
- Force-pushing, rewriting published commits, `--no-verify`.
- Writing back to OneDrive `Health/` or any source-file location. Sources are **read-only**.

Heuristic: "if I'm wrong, what does recovery cost?" Seconds / a re-ingest / a force-push / a privacy leak? Match caution to that cost.

## 3. Simplicity First

Minimum code that solves the problem. Nothing speculative.
- No features beyond what was asked.
- No abstractions for single-use code. A second parser is not a base class.
- No flexibility or configurability that wasn't requested.
- No error handling for impossible scenarios.

Single-user, local-first. No accounts, no auth, no multi-tenancy, no RBAC. If a feature only makes sense for a SaaS, it doesn't make sense here.

## 4. Surgical Changes

Touch only what you must. Stay in your owned paths (see [`AGENTS.md`](AGENTS.md)).
- Don't "improve" adjacent code.
- Don't refactor things that aren't broken.
- Match existing style.
- If you notice a bug outside your lane, note it in `docs/CROSS_AGENT_NOTES.md` — don't fix it.
- Clean up only imports/variables your own changes orphaned.

Every changed line should trace directly to the user's request.

## 5. Goal-Driven Execution

Transform tasks into verifiable goals:
- "Add a bloodwork parser" → "Run it against `w_data/bloodwork.csv`; assert N rows in `labs` with the right `metric` / `unit` / `ref_low`."
- "Fix the dashboard chart" → "Open in Streamlit; verify the chart renders with real data; screenshot or describe what changed."
- "Refactor parser X" → "Snapshot the rows it produces; run; diff should be empty."

For multi-step tasks, state a brief plan with verification per step. Strong success criteria let you loop independently; weak ones ("make it work") require constant clarification.

Checkpoint after every significant step. Don't continue from a state you can't describe back.

## 6. Use the Model Only for Judgment Calls

**If code can answer, code answers.**

- LLM is for: PDF table extraction, narrative summarization, free-text annotation, cross-domain judgment in the dashboard.
- LLM is **not** for: deterministic parsing, unit conversion, date math, filtering, joining tables, dispatching between parsers. Use Python / SQL / pandas / duckdb.
- Reaching for an LLM call where a `dict[str, Parser]` or `pd.merge` would do is a bug, not a feature.

## 7. Fail Loud

- "Ingest complete" is wrong if any source file was skipped silently. Print the skip + reason.
- "Tests pass" is wrong if any were skipped.
- If you guessed at a heuristic, say you guessed.
- Fail loudly at startup for missing config (e.g. `ANTHROPIC_API_KEY`) rather than silently at runtime.

## 8. Privacy Is Not a Feature — It's a Boundary

Will has opted to open-source his own data. Two non-negotiable carve-outs:

- **`private/`** — pedigree containing a living minor (Mattie's GEDCOM) and any other non-consenting-third-party data. **Gitignored. Never commit. Never send to a cloud LLM.**
- **`analysis/`** — derived artifacts including `health.db` and exports. Gitignored; agents regenerate locally.

Additional rules:
- **No raw rsids or genotypes to cloud LLMs** even though they're in the public repo. Derived traits and summary stats only. This is the genome agent's hardest rule and applies to anyone who touches genome data.
- **OneDrive `Health/`** is the user's canonical archive and is **read-only** to this repo. Parse from there or from `w_data/`; never write back.
- `health.db` was previously leaked in git history. As of the most recent purge it's gone from the remote — but anyone who cloned before the purge still has it. Do not re-introduce it; do not commit it; do not push branches that include it in their history.

If your task seems to require violating any of the above, **stop and ask the user**.

## 9. Context Budget — Dump and Start Fresh at 50%

When the conversation passes 50% of the running model's max context (Opus 4.7 = ~500K tokens):
1. Finish the current step — don't reset mid-edit.
2. Dump a handoff to `HANDOFF.md` at the repo root (gitignored, overwrite prior).
3. Alert the user, point at `HANDOFF.md`.
4. Continue in a fresh session seeded only from that file.

Surface the breach explicitly. Don't silently overrun and let quality degrade.

## 10. Documentation Hygiene

After every meaningful change, update what got stale:
- `AGENTS.md` — only the **orchestrator** edits this normally; ingest agents shouldn't touch it.
- `docs/ORCHESTRATION.md` — orchestrator-owned.
- `docs/SCHEMA.md` — schema agent writes when schema lands; everyone reads.
- `docs/CROSS_AGENT_NOTES.md` — **anyone may append** their out-of-lane observations. Don't edit others' entries.
- `docs/INDEX.md` — add an entry when a new doc lands.
- Memory at `C:\Users\Craig UHES\.claude\projects\C--Code-home-projects-health\memory\` — update when source layouts move or stance changes.

**New docs default to `docs/`.** Only files that must be at root for tooling or protocol reasons stay there: `CLAUDE.md` (auto-loaded by Claude Code), `AGENTS.md` (cross-branch registry, fixed path required), `README.md` (convention).

**Commit when satisfied — as a rule.** When work reaches a coherent stopping point, commit and push your branch. Uncommitted work is invisible to the orchestrator. Master merges still need an explicit signal from Will (see [`docs/WORKFLOW.md`](docs/WORKFLOW.md)) **or** are performed by the orchestrator's `/loop` when it sees a `[<agent>] done: ...` commit.

---

## Project at a glance

| Aspect | This repo |
|---|---|
| Stack | Python 3.12 + SQLite + Streamlit (per `docs/ORCHESTRATION.md`) |
| Schema | `schema.sql` at repo root, owned by the **schema** agent — source of truth for all tables |
| Integration | SQLite (`analysis/health.db`) as the integration bus; each agent writes its owned tables, reads others' |
| Data flow | `w_data/` (raw, public) + `private/` (raw, secret) → ingest parsers → SQLite tables → Streamlit |
| Idempotency | Each ingest is `DELETE FROM <my_tables>; INSERT ...` — re-runnable, no append-with-dupes |
| Agents | 6 domains: schema, bloodwork, nutrition, genome, body, dashboard. See [`AGENTS.md`](AGENTS.md). |
| Branches | Each agent works on `agent/<name>` in its own worktree |
| Orchestrator | Watches `agent/*` for `[<agent>] done: ...` commits and merges to master |

### What this is NOT
- Not a SaaS. One user.
- Not a replacement for a doctor. Insights end with "discuss with provider."
- Not a research tool. n=1.
- Not a wearable-streaming platform. Daily batch ingest is enough.
