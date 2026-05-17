# SCHEMA.md — Tables of `analysis/health.db`

Authoritative reference for every ingest agent and the dashboard. The SQL
definitions live in [`../schema.sql`](../schema.sql) at the repo root; this
file is the prose companion.

- **Owner:** the **schema** agent (this file + `schema.sql`).
- **Readers:** every other agent.
- **Idempotency:** each ingest does `DELETE FROM <my_tables>; INSERT ...` —
  re-runnable without dupes (see [`../AGENTS.md`](../AGENTS.md) hard rules).
- **Dates:** ISO-8601 `YYYY-MM-DD` stored as `TEXT`. SQLite has no `DATE`.
- **Foreign keys:** enabled via `PRAGMA foreign_keys = ON;`. Only used
  across `pedigree_conditions → pedigree` (both owned by the genome agent).
- **Privacy:** see [`../CLAUDE.md`](../CLAUDE.md) §8 and the per-table
  caveats below. `snps` and `pedigree*` never leave the host as raw rows
  (see [`LLM_INTERFACE.md`](LLM_INTERFACE.md) §3).

---

## 1. `labs`

Bloodwork results — one row per (date, metric).

- **Owner:** `bloodwork` agent.
- **Idempotency:** `DELETE FROM labs WHERE source_file = ?` then re-insert
  per source file; or full-table `DELETE` + re-INSERT.
- **Columns:** `id`, `date`, `metric`, `value`, `unit`, `ref_low`, `ref_high`,
  `source_file`, `lab_provider`, `notes`.
- **Indexes:** `(metric, date)`, `(date)`.
- **Example:** `(date='2025-10-21', metric='LDL', value=98, unit='mg/dL',
  ref_low=0, ref_high=99, source_file='Craig,William10212025.pdf',
  lab_provider='Labcorp')`.
- **Caveats:** `metric` is the bloodwork agent's canonicalized name (e.g.
  `'LDL'`, not `'LDL Cholesterol Direct'`). Unit normalization is the
  bloodwork agent's job; values stored in canonical unit per metric.

## 2. `nutrition_daily`

One row per (day, source). MacroFactor, Health.xlsx, etc.

- **Owner:** `nutrition` agent.
- **Idempotency:** `DELETE FROM nutrition_daily WHERE source = ?` then
  re-insert.
- **Columns:** `date`, `kcal`, `protein_g`, `carb_g`, `fat_g`, `fiber_g`,
  `sugar_g`, `sodium_mg`, `source`, `source_file`. **PK** `(date, source)`.
- **Indexes:** `(date)`.
- **Example:** `(date='2026-01-02', kcal=2480, protein_g=210, carb_g=240,
  fat_g=78, fiber_g=35, sugar_g=42, sodium_mg=2800, source='macrofactor',
  source_file='MacroFactor-20260102211201.csv')`.
- **Caveats:** macros in grams, sodium in mg. Multiple sources per day are
  allowed (composite key), so the dashboard chooses which to render.

## 3. `snps`

Raw genotype rows from AncestryDNA + similar. **Never exposed to the LLM.**

- **Owner:** `genome` agent.
- **Idempotency:** `DELETE FROM snps; INSERT ...`.
- **Columns:** `rsid` (PK), `chromosome`, `position`, `genotype`, `source`.
- **Indexes:** `(chromosome)`.
- **Example:** `(rsid='rs429358', chromosome='19', position=45411941,
  genotype='TT', source='ancestrydna_2024')`.
- **Privacy:** [`LLM_INTERFACE.md`](LLM_INTERFACE.md) §3 forbids any
  `get_snps` tool. The privacy filter ([`LLM_INTERFACE.md`](LLM_INTERFACE.md)
  §4) refuses outbound rsid/genotype tokens. Public in the repo but never
  in a cloud LLM call.

## 4. `traits`

Derived genome traits (Promethease / FoundMyFitness / calculator outputs).
This is what the LLM and dashboard see in place of `snps`.

- **Owner:** `genome` agent.
- **Idempotency:** `DELETE FROM traits WHERE source = ?` then re-insert.
- **Columns:** `trait`, `category`, `value`, `source`, `confidence`, `notes`.
  **PK** `(trait, source)`.
- **Indexes:** `(category)`.
- **Example:** `(trait='APOE genotype', category='cardiometabolic',
  value='ε3/ε4', source='promethease', confidence=0.95, notes=NULL)`.
- **Caveats:** `value` is `TEXT` because traits are mixed-type (genotype
  strings, percentile bands, free text). Numerical traits should still
  serialize as text for uniform handling.

## 5. `pedigree`

Family tree, **relationship-coded only** — no names. Sourced from
gitignored `private/` GEDCOM containing a living minor.

- **Owner:** `genome` agent.
- **Idempotency:** `DELETE FROM pedigree; INSERT ...`.
- **Columns:** `person_id` (PK), `relationship`, `sex`, `birth_year`,
  `death_year`, `source`.
- **Indexes:** `(relationship)`.
- **Example:** `(person_id='p042', relationship='paternal grandfather',
  sex='M', birth_year=1928, death_year=2002, source='craig_gedcom')`.
- **Privacy:** rows derive from `private/` (gitignored). Names are
  deliberately omitted at parse time per [`../CLAUDE.md`](../CLAUDE.md) §8.
  No tool in [`LLM_INTERFACE.md`](LLM_INTERFACE.md) reads this table.

## 6. `pedigree_conditions`

Health conditions attached to pedigree entries (VISION.md §2). Source
quality starts low and improves as Will annotates.

- **Owner:** `genome` agent.
- **Idempotency:** `DELETE FROM pedigree_conditions; INSERT ...`.
- **Columns:** `person_id` (FK → `pedigree.person_id`), `condition`,
  `age_at_onset`, `source`, `confidence`.
- **Indexes:** `(person_id)`, `(condition)`.
- **Example:** `(person_id='p042', condition='myocardial infarction',
  age_at_onset=58, source='gedcom_note', confidence=0.7)`.
- **Caveats:** `condition` is free string / ICD-ish bucket — no controlled
  vocabulary yet. Same privacy posture as `pedigree`.

## 7. `body_comp`

DEXA snapshots. One row per scan date.

- **Owner:** `body` agent.
- **Idempotency:** `DELETE FROM body_comp WHERE source_file = ?` (or full
  truncate).
- **Columns:** `date` (PK), `bf_pct`, `lbm_kg`, `fat_mass_kg`, `vat_g`,
  `bmd`, `source_file`.
- **Example:** `(date='2022-03-03', bf_pct=18.4, lbm_kg=72.1,
  fat_mass_kg=16.2, vat_g=620, bmd=1.22,
  source_file='William Craig 3-3-22 Dexa Body Composition Report v2024.pdf')`.

## 8. `lifts`

Strength-training entries. Many rows per (date, lift) allowed (sets).

- **Owner:** `body` agent.
- **Idempotency:** `DELETE FROM lifts WHERE source_file = ?` per workbook.
- **Columns:** `date`, `lift`, `weight_kg`, `reps`, `sets`, `e1rm`,
  `source_file`.
- **Indexes:** `(lift, date)`, `(date)`.
- **Example:** `(date='2025-03-14', lift='back squat', weight_kg=160,
  reps=5, sets=3, e1rm=180, source_file='2025 Lifts.xlsx')`.
- **Caveats:** weight in kg (convert lb at parse time). `e1rm` is the
  body agent's choice of estimator (Epley/Brzycki/etc.) — record the
  same formula consistently.

## 9. `sleep`

Daily sleep duration and stages. One row per (date, source).

- **Owner:** `body` agent.
- **Idempotency:** `DELETE FROM sleep WHERE source = ?` then re-insert.
- **Columns:** `date`, `total_hr`, `rem_hr`, `deep_hr`, `light_hr`,
  `awake_hr`, `hr_avg`, `source`. **PK** `(date, source)`.
- **Indexes:** `(date)`.
- **Example:** `(date='2023-11-12', total_hr=7.3, rem_hr=1.5, deep_hr=1.1,
  light_hr=4.4, awake_hr=0.3, hr_avg=58.2, source='oura')`.

## 10. `events`

Thin cross-domain timeline. The dashboard reads this to render "what
happened on day X" without joining seven tables.

- **Owner:** every ingest agent appends its own rows (e.g. bloodwork
  inflections, lift PRs, DEXA scans). The synthesis layer also writes.
- **Idempotency:** each writer deletes by `domain` + `event_type`
  range before re-inserting (e.g. `DELETE FROM events WHERE domain='labs'
  AND event_type='inflection'`).
- **Columns:** `id` (PK), `date`, `domain`, `event_type`, `summary`,
  `payload_json`.
- **Indexes:** `(date)`, `(domain, date)`.
- **Example:** `(date='2025-10-21', domain='labs', event_type='inflection',
  summary='HDL crossed lab ref_high', payload_json='{"metric":"HDL",...}')`.
- **LLM exposure:** the `get_events` tool exposes `summary` but strips
  `payload_json` ([`LLM_INTERFACE.md`](LLM_INTERFACE.md) §3).

## 11. `nutrient_targets`

Personalized RDIs computed by the YAML calculators (VISION.md §3).

- **Owner:** the calculators loader (lives in `analysis/calculators/`, not
  an ingest agent yet; treated as a synthesis-layer writer).
- **Idempotency:** `DELETE FROM nutrient_targets; INSERT ...` on each
  load — the YAML files are the source of truth.
- **Columns:** `nutrient` (PK), `target_value`, `unit`,
  `computed_from_json`, `computed_at`.
- **Example:** `(nutrient='choline_mg', target_value=700, unit='mg',
  computed_from_json='{"base":550,"snp_increments":{"rs7946":50,"rs12325817":100}}',
  computed_at='2026-05-16T20:14:03Z')`.

## 12. `risk_scores`

Risk-score outputs (VISION.md §1). One row per (date, score_id).

- **Owner:** `risk` agent (consumer-only — reads `labs`/`traits`/
  `pedigree`/`body_comp`, writes here, never writes other tables).
- **Idempotency:** `DELETE FROM risk_scores WHERE date = ? AND score_id = ?`
  before each compute.
- **Columns:** `date`, `score_id`, `source`, `value`, `percentile`,
  `inputs_json`, `notes`. **PK** `(date, score_id)`.
- **Indexes:** `(score_id)`.
- **Example:** `(date='2026-05-16', score_id='phenoage', source='levine_2018',
  value=38.2, percentile=22, inputs_json='{"lab_ids":[101,102,...]}',
  notes=NULL)`.

## 13. `ingest_meta`

Each ingest writes one row when it completes; the freshness footer reads
this to show "as of when, how many rows, from where."

- **Owner:** every ingest agent (one row per `source` key it owns).
- **Idempotency:** `INSERT OR REPLACE INTO ingest_meta (source, ...)` —
  PK on `source` makes the upsert clean.
- **Columns:** `source` (PK), `last_run`, `n_rows`, `source_file`, `notes`.
- **Example:** `(source='bloodwork', last_run='2026-05-16T20:30:01Z',
  n_rows=412, source_file='w_data/bloodwork.csv', notes=NULL)`.

---

## Load order

```
sqlite3 analysis/health.db < schema.sql      # create tables
# then in any order, parallel:
python -m ingest.bloodwork                   # writes labs
python -m ingest.nutrition                   # writes nutrition_daily
python -m ingest.genome                      # writes snps, traits, pedigree, pedigree_conditions
python -m ingest.body                        # writes body_comp, lifts, sleep
# then (synthesis layer, downstream consumers):
python -m analysis.calculators.load          # writes nutrient_targets
python -m analysis.risk                      # writes risk_scores
```

Each step records its own row in `ingest_meta`.
