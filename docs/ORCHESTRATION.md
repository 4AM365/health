# Orchestration Plan

A personal health intelligence dashboard for Will Craig, built by parallel domain agents coordinated through git. Single-user, local-first, privacy-preserving.

## Domains

Each domain is owned by one agent in its own session/worktree. Agents work in parallel after the schema lands.

| # | Agent | Owns | Inputs | Output |
|---|-------|------|--------|--------|
| 1 | **Schema** | `schema.sql`, migrations, `docs/SCHEMA.md` | nothing (designs from scratch) | tables: `labs`, `nutrition_daily`, `snps`, `traits`, `pedigree`, `body_comp`, `lifts`, `sleep`, `events` |
| 2 | **Bloodwork** | `ingest/bloodwork/` | `w_data/bloodwork.csv`, Labcorp/Quest PDFs, `Blood_Test_Results.csv` | rows in `labs` |
| 3 | **Nutrition** | `ingest/nutrition/` | `MacroFactor-*.csv`, `Health.xlsx` | rows in `nutrition_daily` |
| 4 | **Genome+Pedigree** | `ingest/genome/` | `w_data/2024 Data/wc-dna-data-*/AncestryDNA.txt`, Promethease, FoundMyFitness, `private/craig_gedcom/*.ged`, `private/Craig Family Tree.zip` | rows in `snps`, `traits`, `pedigree` — **pedigree contains a living minor; never commit `private/`; no raw genotypes to cloud LLMs** |
| 5 | **Body+Sleep** | `ingest/body/` | DEXA PDFs, `2025 Lifts.xlsx`, `Sleep*.csv/png`, `Sleep_Processed.xlsx` | rows in `body_comp`, `lifts`, `sleep` |
| 6 | **Dashboard** | `app/` | `health.db` (read-only) | local Streamlit app showing trends + cross-domain views |

Per-agent hard rules and the startup protocol live in [`AGENTS.md`](../AGENTS.md).

## Software Structure

```
health/
├── schema.sql             # source of truth (Schema agent owns)
├── AGENTS.md              # agent registry + startup protocol
├── .gitignore             # excludes private/, analysis/, *.db
├── ingest/
│   ├── bloodwork/         # parsers → INSERT INTO labs
│   ├── nutrition/
│   ├── genome/
│   ├── body/
│   └── _shared/           # date parsing, unit normalization
├── app/
│   ├── main.py            # Streamlit entry
│   └── views/             # one view per cross-domain insight
├── docs/
│   ├── INDEX.md
│   ├── ORCHESTRATION.md   # this file
│   ├── SCHEMA.md          # Schema agent writes when done
│   └── CROSS_AGENT_NOTES.md  # out-of-lane observations
├── w_data/                # tracked: Will's own raw data (genome, bloodwork, DEXA, nutrition, sleep, lifts)
├── private/               # GITIGNORED: pedigree with living minors (GEDCOM)
└── analysis/              # GITIGNORED: derived artifacts — health.db, exports
```

### Design choices

- **SQLite as integration bus.** Every agent writes its tables and reads others'. No service mesh, no API contracts beyond `schema.sql`. Fully parallel after schema lands.
- **Ingest separated from app.** Re-running an ingest never touches the UI. UI is pure read.
- **Streamlit for v1 UI.** Local, Python, no auth/hosting — matches single-user local-first.
- **`events` table** as a thin cross-domain timeline (`date, domain, event_type, payload_json`) so the dashboard can render "what happened on day X" without joining 7 tables. Each ingest agent populates its own rows.

### Critical path

```
Schema ──► (Bloodwork, Nutrition, Genome+Pedigree, Body+Sleep — parallel) ──► Dashboard
```

Dashboard can stub against a fake DB until ingests start landing.

### Conflict surface

Only `schema.sql`. `health.db` (now under `analysis/`) is gitignored. Cross-agent observations go in `docs/CROSS_AGENT_NOTES.md` — append-only, no edits to others' entries.

### Privacy posture

Will has opted to open-source his own data — `w_data/` is tracked and public. Two carve-outs:
- **`private/`** holds the GEDCOM containing a living minor (Mattie) and any other non-consenting-third-party data. Gitignored; never commit.
- **`analysis/`** holds derived artifacts (`health.db`, exports). Gitignored; agents regenerate locally.

Genome agent additionally never sends raw rsids/genotypes to cloud LLMs even though they're in the public repo — derived traits and summary stats only.

## Orchestrator loop

The orchestrator runs `/loop 15m` watching `agent/*` branches for `[<agent>] done: ...` commits. Each one is a merge signal. Clean merges (no conflicts, only touches owned paths) go to master automatically. Conflicts pause the loop and surface to Will.
