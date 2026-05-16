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
| **genome** | `agent/genome` | `ingest/genome/`, tables: `snps`, `traits`, `pedigree`. Reads pedigree from gitignored `private/` | `[genome] done: <summary>` |
| **body** | `agent/body` | `ingest/body/`, tables: `body_comp`, `lifts`, `sleep` | `[body] done: <summary>` |
| **dashboard** | `agent/dashboard` | `app/` | `[dashboard] done: <summary>` |

## Hard rules every agent inherits

- **Schema agent commits first.** Other ingest agents block on `schema.sql` existing on master.
- **No cross-domain writes.** You write only your owned tables. To consume another domain's data, read its tables.
- **`health.db` lives in `analysis/`** and is gitignored. Agents regenerate it locally by running ingests.
- **Idempotent ingests.** Re-running your parser is `DELETE FROM <my_tables>; INSERT ...`. No append-with-dupes.
- **Source-file locations:**
  - `w_data/` — Will's own data (genome, bloodwork, DEXA, nutrition, sleep, lifts). Tracked + public.
  - `private/` — pedigree containing living minors (Mattie's GEDCOM). **Gitignored. Never commit.**
  - `analysis/` — derived artifacts including `health.db`. Gitignored.
  - Parse against the real files at these paths; never fabricate sample data to make tests pass.
- **Privacy:** Will has opted to open-source his own data. Two hard exceptions: (1) `private/` content (GEDCOM with minors) never gets committed or sent to a cloud LLM, (2) the genome agent does not send raw rsids/genotypes to cloud LLMs even though they're in the public repo — derived traits only.
- **Stay in your lane.** If you find a bug outside your owned paths, note it in `docs/CROSS_AGENT_NOTES.md` — don't fix it.

## Orchestrator's job

- Maintains `docs/ORCHESTRATION.md` and this file.
- Runs the /loop that watches `agent/*` branches for `done` commits.
- Merges clean commits to `master`. Resolves cross-agent conflicts.
- Does **not** write parsers or app code itself.
