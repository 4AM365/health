# AGENTS.md — Multi-Agent Coordination Registry

This repo is built by an **orchestrator** + parallel **domain agents**, each running in its own Claude Code session and worktree. This file is the registry: every agent reads it on startup to find its role.

**Read first:** [docs/ORCHESTRATION.md](docs/ORCHESTRATION.md) for the full plan and software structure.

## How a domain agent starts

1. Open a fresh Claude Code session in this repo.
2. Read this file to find your assigned role + branch.
3. Read `docs/ORCHESTRATION.md` for the full plan.
4. Read `docs/<your-agent>.md` if one exists (schema contract, etc.).
5. Create your worktree: `git worktree add ../<agent-name> -b agent/<agent-name> master`
6. Work only inside your **Owned paths**. Read other tables; never write them.
7. When done, commit on your branch with message `[<agent>] done: <one-line summary>`. Push it.
8. Orchestrator's /loop picks up your commit and merges to master.

## Agent Registry

| Agent | Branch | Owned paths | Done signal |
|---|---|---|---|
| **schema** | `agent/schema` | `schema.sql`, `docs/SCHEMA.md` | `[schema] done: <summary>` |
| **bloodwork** | `agent/bloodwork` | `ingest/bloodwork/`, tables: `labs` | `[bloodwork] done: <summary>` |
| **nutrition** | `agent/nutrition` | `ingest/nutrition/`, tables: `nutrition_daily` | `[nutrition] done: <summary>` |
| **genome** | `agent/genome` | `ingest/genome/`, tables: `snps`, `traits`, `pedigree` | `[genome] done: <summary>` |
| **body** | `agent/body` | `ingest/body/`, tables: `body_comp`, `lifts`, `sleep` | `[body] done: <summary>` |
| **dashboard** | `agent/dashboard` | `app/` | `[dashboard] done: <summary>` |

## Hard rules every agent inherits

- **Schema agent commits first.** Other ingest agents block on `schema.sql` existing on master.
- **No cross-domain writes.** You write only your owned tables. To consume another domain's data, read its tables.
- **`health.db` is not committed.** Agents regenerate it locally by running ingests. Add to `.gitignore` if not already.
- **Idempotent ingests.** Re-running your parser is `DELETE FROM <my_tables>; INSERT ...`. No append-with-dupes.
- **Real data only.** Source files live in `w_data/` and `C:\Users\Craig UHES\OneDrive\Health\`. Parse against the real files; never fabricate sample data to make tests pass.
- **Privacy (genome agent especially):** raw rsids / genotypes never leave the machine. No cloud LLM calls with raw genome rows. Pedigree contains a living minor (Mattie) — treat carefully.
- **Stay in your lane.** If you find a bug outside your owned paths, note it in `docs/CROSS_AGENT_NOTES.md` — don't fix it.

## Orchestrator's job

- Maintains `docs/ORCHESTRATION.md` and this file.
- Runs the /loop that watches `agent/*` branches for `done` commits.
- Merges clean commits to `master`. Resolves cross-agent conflicts.
- Does **not** write parsers or app code itself.
