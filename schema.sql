-- schema.sql — single source of truth for the health repo's SQLite database.
--
-- Owned by the **schema** agent (see AGENTS.md). Every other ingest agent's
-- INSERT statements must match the tables defined here. Re-running this file
-- from scratch (`sqlite3 analysis/health.db < schema.sql`) yields an empty
-- database with every table + index every domain depends on.
--
-- Load order: this file first, then each ingest agent populates its own
-- tables with `DELETE FROM <my_tables>; INSERT ...` (idempotent per
-- AGENTS.md hard rules). No cross-domain writes.
--
-- Conventions:
--   - All dates are ISO-8601 TEXT (`YYYY-MM-DD`). SQLite has no DATE type;
--     storing as TEXT keeps comparisons + indexes correct.
--   - Every table has a primary key that supports idempotent re-runs.
--   - `*_json` columns hold opaque payloads serialized by the writing agent.
--   - Tables grouped by domain in load-order-irrelevant blocks (no FK
--     between domains; the only cross-table FK is pedigree_conditions →
--     pedigree, both owned by the genome agent).
--
-- Privacy carve-outs (also see CLAUDE.md §8):
--   - `snps` is **never** exposed to the LLM (LLM_INTERFACE.md §3).
--   - `pedigree` and `pedigree_conditions` are sourced from gitignored
--     `private/` GEDCOM containing a living minor. Names are deliberately
--     omitted — pedigree is relationship-coded only.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- 1. labs — bloodwork agent
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS labs (
    id            INTEGER PRIMARY KEY,
    date          TEXT    NOT NULL,
    metric        TEXT    NOT NULL,
    value         REAL,
    unit          TEXT,
    ref_low       REAL,
    ref_high      REAL,
    source_file   TEXT,
    lab_provider  TEXT,
    notes         TEXT
);

CREATE INDEX IF NOT EXISTS idx_labs_metric_date ON labs (metric, date);
CREATE INDEX IF NOT EXISTS idx_labs_date        ON labs (date);

-- ---------------------------------------------------------------------------
-- 2. nutrition_daily — nutrition agent
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nutrition_daily (
    date          TEXT NOT NULL,
    kcal          REAL,
    protein_g     REAL,
    carb_g        REAL,
    fat_g         REAL,
    fiber_g       REAL,
    sugar_g       REAL,
    sodium_mg     REAL,
    source        TEXT NOT NULL,
    source_file   TEXT,
    PRIMARY KEY (date, source)
);

CREATE INDEX IF NOT EXISTS idx_nutrition_daily_date ON nutrition_daily (date);

-- ---------------------------------------------------------------------------
-- 3. snps — genome agent. NEVER exposed to the LLM (LLM_INTERFACE.md §3).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS snps (
    rsid          TEXT PRIMARY KEY,
    chromosome    TEXT,
    position      INTEGER,
    genotype      TEXT,
    source        TEXT
);

CREATE INDEX IF NOT EXISTS idx_snps_chromosome ON snps (chromosome);

-- ---------------------------------------------------------------------------
-- 4. traits — genome agent (derived genome traits; LLM-exposed)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS traits (
    trait         TEXT NOT NULL,
    category      TEXT,
    value         TEXT,
    source        TEXT NOT NULL,
    confidence    REAL,
    notes         TEXT,
    PRIMARY KEY (trait, source)
);

CREATE INDEX IF NOT EXISTS idx_traits_category ON traits (category);

-- ---------------------------------------------------------------------------
-- 5. pedigree — genome agent. Sourced from gitignored private/ GEDCOM.
--    Relationship-coded only; names deliberately omitted.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pedigree (
    person_id     TEXT PRIMARY KEY,
    relationship  TEXT,
    sex           TEXT,
    birth_year    INTEGER,
    death_year    INTEGER,
    source        TEXT
);

CREATE INDEX IF NOT EXISTS idx_pedigree_relationship ON pedigree (relationship);

-- ---------------------------------------------------------------------------
-- 6. pedigree_conditions — genome agent (VISION.md §2).
--    Free-text/ICD-ish health conditions tied to pedigree entries.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pedigree_conditions (
    person_id     TEXT NOT NULL,
    condition     TEXT NOT NULL,
    age_at_onset  INTEGER,
    source        TEXT,
    confidence    REAL,
    FOREIGN KEY (person_id) REFERENCES pedigree (person_id)
);

CREATE INDEX IF NOT EXISTS idx_pedigree_conditions_person    ON pedigree_conditions (person_id);
CREATE INDEX IF NOT EXISTS idx_pedigree_conditions_condition ON pedigree_conditions (condition);

-- ---------------------------------------------------------------------------
-- 7. body_comp — body agent (DEXA snapshots)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS body_comp (
    date          TEXT PRIMARY KEY,
    bf_pct        REAL,
    lbm_kg        REAL,
    fat_mass_kg   REAL,
    vat_g         REAL,
    bmd           REAL,
    source_file   TEXT
);

-- ---------------------------------------------------------------------------
-- 8. lifts — body agent
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lifts (
    date          TEXT NOT NULL,
    lift          TEXT NOT NULL,
    weight_kg     REAL,
    reps          INTEGER,
    sets          INTEGER,
    e1rm          REAL,
    source_file   TEXT
);

CREATE INDEX IF NOT EXISTS idx_lifts_lift_date ON lifts (lift, date);
CREATE INDEX IF NOT EXISTS idx_lifts_date      ON lifts (date);

-- ---------------------------------------------------------------------------
-- 9. sleep — body agent
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sleep (
    date          TEXT NOT NULL,
    total_hr      REAL,
    rem_hr        REAL,
    deep_hr       REAL,
    light_hr      REAL,
    awake_hr      REAL,
    hr_avg        REAL,
    source        TEXT NOT NULL,
    PRIMARY KEY (date, source)
);

CREATE INDEX IF NOT EXISTS idx_sleep_date ON sleep (date);

-- ---------------------------------------------------------------------------
-- 10. events — cross-domain timeline. Every ingest agent appends its own
--     rows (lab inflections, PRs, etc.); the synthesis layer also writes.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY,
    date          TEXT NOT NULL,
    domain        TEXT NOT NULL,
    event_type    TEXT,
    summary       TEXT,
    payload_json  TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_date          ON events (date);
CREATE INDEX IF NOT EXISTS idx_events_domain_date   ON events (domain, date);

-- ---------------------------------------------------------------------------
-- 11. nutrient_targets — calculators loader (VISION.md §3).
--     Gene-adjusted personalized RDIs, one row per nutrient.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nutrient_targets (
    nutrient            TEXT PRIMARY KEY,
    target_value        REAL,
    unit                TEXT,
    computed_from_json  TEXT,
    computed_at         TEXT
);

-- ---------------------------------------------------------------------------
-- 12. risk_scores — risk agent (VISION.md §1).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS risk_scores (
    date          TEXT NOT NULL,
    score_id      TEXT NOT NULL,
    source        TEXT,
    value         REAL,
    percentile    REAL,
    inputs_json   TEXT,
    notes         TEXT,
    PRIMARY KEY (date, score_id)
);

CREATE INDEX IF NOT EXISTS idx_risk_scores_score_id ON risk_scores (score_id);

-- ---------------------------------------------------------------------------
-- 13. ingest_meta — each ingest writes one row when it completes.
--     The dashboard's freshness footer reads this.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingest_meta (
    source        TEXT PRIMARY KEY,
    last_run      TEXT,
    n_rows        INTEGER,
    source_file   TEXT,
    notes         TEXT
);
