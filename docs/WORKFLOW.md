# Git + Branch Workflow

How code flows from an agent's worktree to master. Read on every session via [`../CLAUDE.md`](../CLAUDE.md). Update here first; mirror to memory at `~/.claude/projects/C--Code-home-projects-health/memory/` if the policy changes.

This repo is a **single-user, local-first** dashboard. There's no production deploy, no preview build. Master is just "the version Will trusts to run against his actual `analysis/health.db`."

---

## Rules

1. **Each agent works on its own branch** named per [`AGENTS.md`](../AGENTS.md): `agent/schema`, `agent/bloodwork`, etc. Create with `git worktree add ../<name> -b agent/<name> master`.

2. **Always push the branch you commit on.** After `git commit`, run `git push -u origin HEAD` (or just `git push` if tracked). Pushed work is visible to the orchestrator; unpushed work is invisible and gets lost at merge time.

3. **Use the done signal.** When your domain work is complete, commit with message `[<agent>] done: <one-line summary>`. The orchestrator's `/loop` watches for this pattern and merges your branch to master.

4. **Never push to master yourself.** Don't run `git push origin HEAD:master`, `git merge` against master, or anything else that updates master. The orchestrator (or Will directly) is the only writer to master.

5. **Worktree branches stay alive.** Don't delete the `agent/<name>` branch on the remote after merging. The branch is the audit trail for what shipped.

6. **Force-pushing to master is never authorized** without an explicit, scoped instruction from Will. Authorization for one merge does not carry over.

7. **`--no-verify` and other hook-skipping flags** require explicit per-commit authorization. Treat hook failures as bugs.

8. **Never commit data.** The `.gitignore` excludes `private/`, `analysis/`, `*.db`, `*.sqlite*`. If you find yourself wanting to bypass it, stop and ask. Data committed to a public repo is essentially permanent — recovery requires a history rewrite (see "After a history rewrite" below).

9. **Schema changes need a migration, not in-place edits.** `schema.sql` is the source of truth; it's owned by the **schema** agent. If you're not schema, propose your change in `docs/CROSS_AGENT_NOTES.md` rather than editing `schema.sql`.

---

## Quick reference

| Situation | Do |
|---|---|
| Starting work | `git worktree add ../<agent> -b agent/<agent> master` per AGENTS.md step 5 |
| Just committed | `git push -u origin HEAD` (first time) or `git push` (subsequent) |
| Done with your domain | Commit with `[<agent>] done: <summary>` and push; orchestrator merges |
| Found a bug outside your lane | Append a note to `docs/CROSS_AGENT_NOTES.md`; do not fix |
| Want to touch `schema.sql` and you're not schema agent | Propose via `docs/CROSS_AGENT_NOTES.md` |
| Hook fails | Fix the underlying issue. Do not `--no-verify`. |
| Master moved while you were working | The orchestrator will rebase or surface conflicts; you don't merge master into your branch unsupervised |

---

## After a history rewrite

If `git filter-repo` or similar has rewritten history (e.g. the May 2026 `health.db` purge), every active agent must:

1. **Stop work.**
2. Save any in-progress diff to a patch file: `git diff master -- > /tmp/<agent>-wip.patch`.
3. Delete the worktree: `git worktree remove ../<agent> --force`.
4. Fetch the rewritten master: `git fetch origin master && git reset --hard origin/master` in the main repo.
5. Recreate the worktree off the new master per AGENTS.md.
6. Re-apply the patch if relevant: `git apply /tmp/<agent>-wip.patch`.

A history rewrite invalidates every branch whose commits chain through the rewritten range. Pushing an unsynced branch will reintroduce the bad blobs — that's why the stop-and-reset protocol exists.

---

## What master means here

Master is the version Will is willing to run against his actual data. Two practical implications:

- **A merged commit may be re-run against real data.** If a parser change might mangle existing rows, surface that risk in the commit message before the orchestrator merges.
- **A merged schema is the schema migrations apply on top of.** Once a migration is on master, you can't rewrite it — you write a new one.

When in doubt about whether something is master-ready, ask. The cost of one clarifying question is much lower than the cost of corrupting `analysis/health.db` or re-leaking data.
