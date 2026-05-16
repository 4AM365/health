# VISION.md — Distinctive Angle and Roadmap

*Architect's proposal, 2026-05-16. Not yet ratified; agents should not implement from this doc until merged and referenced from [`ORCHESTRATION.md`](ORCHESTRATION.md).*

## TL;DR

The current build is "personal health dashboard #N." The distinctive angle hiding in this repo — and not addressed by any open-source competitor — is **family-aware personal health intelligence**: your raw genome + your *living family's* documented health events (GEDCOM) + your longitudinal labs + your daily macros + your body composition, all reasoned about together. Six new pieces (one new agent, two tables, three views) turn the current MVP into something nobody else ships.

## Competitive landscape (scanned 2026-05-16)

| Project | Bloodwork | Genome (raw) | Pedigree/GEDCOM | Nutrition | Wearables | Body comp | Notes |
|---|---|---|---|---|---|---|---|
| [GetBased](https://github.com/elkimek/get-based) | 287+ markers | 47 curated SNPs, APOE, mtDNA | — | — (lifestyle card only) | yes | — | Closest competitor. Strong on bloodwork & SNP UI. |
| [Fasten Health](https://github.com/fastenhealth/fasten-onprem) | EMR-aggregated | — | — | — | — | — | Record aggregator, not analytical. |
| [Mere Medical](https://github.com/cfu288/mere-medical) | EMR-aggregated | — | — | — | — | — | Same as Fasten. |
| [pgsc_calc](https://github.com/PGScatalog/pgsc_calc), [PRScalc](https://academic.oup.com/bioinformaticsadvances/article/3/1/vbad145/7301466) | — | PGS scores | — | — | — | — | Pure PRS pipelines; no longitudinal personal context. |
| [FamGenix](https://famgenix.com/) | — | — | clinical pedigree | — | — | — | Clinician tool; not open, not personal. |
| [snps](https://pypi.org/project/snps/), [SNPedia](https://www.snpedia.com/) | — | parsing + annotation | — | — | — | — | Libraries/wikis, not dashboards. |
| **This repo (current plan)** | yes | yes (47+ SNPs scope) | **yes** | **yes (MacroFactor daily)** | not yet | DEXA + lifts + sleep | Only one with all five. |

**The pedigree column is empty everywhere else.** That is the moat.

## The distinctive angle, stated

> A single-user, local-first dashboard that reasons across your genome, your living family's GEDCOM with conditions, your longitudinal bloodwork, your daily nutrition, and your body/sleep — and writes the conclusions in plain English a non-clinician can act on.

Three things follow from that one sentence:

1. **Family-aware risk.** Genetic counselors charge for pedigree-derived risk because pedigree adds information your genome alone does not (penetrance modifiers, environment, age-of-onset distributions). We can render this for free.
2. **Gene-adjusted nutrient targets.** The Choline calc output already in `w_data/` is one instance of a general pattern: a SNP set defines a personalized RDI. We should treat this as a *plugin type*, not a one-off page.
3. **Plain-English narrative.** Most of these projects render numbers and leave interpretation to the user. The genome/labs/pedigree → narrative step is where most users get stuck. This is where the dashboard should differentiate hardest.

## Proposed software changes (additive, not a rewrite)

All additions fit the existing SQLite-as-bus + per-domain-agent model from [`ORCHESTRATION.md`](ORCHESTRATION.md). No new infra.

### 1. New agent: `risk` (consumer-only)

Reads `snps`, `traits`, `pedigree`, `labs`, `body_comp`. Writes one new table:

```sql
risk_scores(
  date TEXT,           -- when computed
  score_id TEXT,       -- e.g. 'phenoage', 'pgs000018_cad', 'family_cvd_by_age_60'
  source TEXT,         -- 'levine_2018', 'pgs_catalog', 'pedigree_derived'
  value REAL,
  percentile REAL,
  inputs_json TEXT,    -- which lab rows / SNPs / pedigree IDs fed in
  notes TEXT
)
```

Implements:
- **PhenoAge** (Levine 2018, 9 standard labs + chronological age).
- **PGS Catalog scores** for a small curated panel: CAD, T2DM, AD, breast/prostate, LDL. Use [`pgsc_calc`](https://github.com/PGScatalog/pgsc_calc) or a thin custom implementation against [PRScalc](https://academic.oup.com/bioinformaticsadvances/article/3/1/vbad145/7301466)-style logic. **Runs locally; never sends genotypes out.**
- **Pedigree-derived priors**: cause-of-death distribution by relationship-degree and age, family-history flags ("≥2 first-degree relatives with cardiovascular event before age 60").

`risk` is a pure consumer — never writes to any other agent's table. Easy to land last; downstream of all four ingest agents.

### 2. New table: `pedigree_conditions` (genome agent owns)

GEDCOM stores structural genealogy but health conditions are usually in free-text NOTE fields. Add:

```sql
pedigree_conditions(
  person_id TEXT,      -- FK to pedigree
  condition TEXT,      -- ICD-ish bucket or free string
  age_at_onset INT,    -- nullable
  source TEXT,         -- 'gedcom_note', 'manual', 'inferred'
  confidence REAL
)
```

Will populates over time as he annotates family entries. The data quality will start poor and improve — design accepts that.

### 3. New module: `analysis/calculators/` (plugin model)

YAML-declared "gene → nutrient target" calculators. One file per calculator:

```yaml
# analysis/calculators/choline.yaml
nutrient: choline_mg
base_rdi: 550
sex_modifier: { female: 425, male: 550 }
snps:
  - rsid: rs7946        # PEMT
    effect_allele: T
    increment_mg: 50
  - rsid: rs12325817    # CHDH
    effect_allele: G
    increment_mg: 100
  # ...
output_field: choline_target_mg
```

Loader walks YAML, joins to `snps` table, writes per-user targets into a small `nutrient_targets(nutrient, target_value, computed_from_json)` table. Initial set: choline (Masterjohn), folate (MTHFR), caffeine (CYP1A2), alcohol (ALDH2/ADH1B), lactose (LCT). Adding a calculator = writing a YAML file, no Python.

### 4. Dashboard views (three new)

- **`app/views/marker.py`** — per-bloodmarker panel: trend line, your SNPs influencing it (from a `snp→marker` map), the nutrients you eat that influence it (joined from `nutrition_daily` and `nutrient_targets`), the family conditions implicated. *One screen, all four domains.* This is the flagship view.
- **`app/views/family.py`** — GEDCOM-rendered tree (use [`pyvis`](https://pyvis.readthedocs.io/) or [`networkx`](https://networkx.org/) → HTML), with glyphs for conditions/cause-of-death and a click-through to "what this means for you" panel. **Has a privacy toggle**: anonymize to relationship-only labels for screenshots.
- **`app/views/narrative.py`** — generated plain-English summary per domain (labs trending, nutrition gaps, family signals to watch). Powered by a small local-or-API LLM call with **derived data only** — never raw rsids/genotypes, never names from GEDCOM. Respects the genome-agent privacy rule.

### 5. Anonymization helper

`app/_shared/anonymize.py` — single function that takes a pedigree row and returns `("paternal grandfather", age_at_death, conditions)` instead of names + dates. Used by the family view's "share mode" and by anything feeding an LLM.

### 6. (Optional) Wearables ingest

Apple Health / Oura / Whoop export → `wearable_daily` table. Only worth it if Will actually has continuous data. Defer until the above lands.

## Research topics worth making accessible

In rough order of "actionable per dollar":

1. **APOE genotype → cardiovascular + dementia risk.** Single most informative SNP for most people. Will already has APOE through Promethease.
2. **Lp(a) once-in-lifetime test.** Genetically determined; standard bloodwork rarely includes it. Surface "have you tested?" prompt if missing.
3. **PhenoAge biological age** (Levine 2018). Uses 9 routine labs Will already collects.
4. **Methylation panel + MTHFR.** Folate target adjustment; B12/homocysteine watch.
5. **Cause-of-death distribution from pedigree.** A 4-generation tree usually has enough deaths to flag dominant risks. This is what costs $500 at a genetic counselor.
6. **Sleep ↔ metabolic markers.** The sleep CSVs + HbA1c trends from labs already let us correlate.
7. **DEXA + lifts → sarcopenia trajectory.** Project lean-mass loss rate against age cohort.
8. **Polygenic risk scores from the [PGS Catalog](https://www.pgscatalog.org/).** Use only well-validated scores; report as percentile-in-population, not absolute risk.

Each is one paragraph of explainer + one query against the DB + one chart. The narrative view stitches them.

## What we explicitly do NOT add

- No cloud sync, no multi-user, no account system. Stays single-user local-first.
- No EMR aggregation (Fasten/Mere already do that well; not our angle).
- No clinical claims. Every narrative panel ends with "ask your doctor."
- No raw genome data through cloud LLMs. Period. ([`AGENTS.md`](../AGENTS.md) rule.)

## Critical path delta vs current plan

```
Schema ─► (Bloodwork, Nutrition, Genome, Body — parallel) ─► Dashboard
                                                          └─► Risk (new) ─► Dashboard (marker + narrative views)
```

`risk` can ship after any one ingest lands (e.g., PhenoAge needs only `labs`). The pedigree-aware features need `genome` + `pedigree_conditions`.

## Open questions for Will

1. How annotated is the GEDCOM today? If conditions/cause-of-death are mostly missing, the family-aware features degrade to "structural tree only" until you backfill. Worth a one-time annotation pass?
2. PGS scope: full PGS Catalog panel (hundreds of scores) or curated top-10? Recommend curated.
3. Narrative LLM: local (Ollama/llama.cpp) or API with derived-data-only guard? Local avoids the privacy question entirely.
4. Wearables: do you have a continuous export source worth ingesting, or skip for v1?
