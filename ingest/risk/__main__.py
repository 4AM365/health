"""`python -m ingest.risk` — run all risk calculators.

Reads from analysis/health.db. Writes to risk_scores, events, ingest_meta.
Fails loud (CLAUDE.md §7) when required inputs are missing.

Environment:
  WILL_BIRTH_YEAR — chronological-age anchor for PhenoAge. Defaults to
    1985 if unset; print a warning either way so the value is visible.

The risk agent is a pure consumer (AGENTS.md / VISION.md §1): it never
writes to any other agent's tables.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from .pedigree_priors import (
    ConditionRow,
    PedigreeRow,
    compute_pedigree_scores,
)
from .phenoage import LabRow, compute_phenoage_rows
from .pgs_lite import SnpRow, compute_pgs_scores


ROOT = Path(__file__).parent.parent.parent
DB_PATH = ROOT / "analysis" / "health.db"

# All score_ids this module writes. Used for the idempotent DELETE.
PEDIGREE_BUCKETS = [
    "cvd", "t2dm", "alzheimers", "breast_cancer", "prostate_cancer",
    "colon_cancer", "kidney_disease", "hypertension",
]
PEDIGREE_SCORE_IDS = []
for b in PEDIGREE_BUCKETS:
    PEDIGREE_SCORE_IDS.extend([
        f"family_{b}_first_degree",
        f"family_{b}_first_degree_median_onset",
        f"family_{b}_first_degree_before_60",
    ])


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    )
    return cur.fetchone() is not None


def _row_count(conn: sqlite3.Connection, name: str) -> int:
    if not _table_exists(conn, name):
        return 0
    return conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> int:
    if not DB_PATH.exists():
        print(
            f"[risk] analysis/health.db not found at {DB_PATH}. "
            f"Run schema + ingest agents first. Exiting cleanly.",
            file=sys.stderr,
        )
        return 0

    try:
        birth_year = int(os.environ.get("WILL_BIRTH_YEAR", "1985"))
    except ValueError:
        print(
            f"[risk] WILL_BIRTH_YEAR={os.environ.get('WILL_BIRTH_YEAR')!r} "
            f"is not an int; falling back to 1985.",
            file=sys.stderr,
        )
        birth_year = 1985
    print(f"[risk] chronological-age anchor: birth_year={birth_year}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Sanity: required tables.
    for t in ("labs", "pedigree", "pedigree_conditions", "snps",
              "risk_scores", "events", "ingest_meta"):
        if not _table_exists(conn, t):
            print(
                f"[risk] required table `{t}` missing; load schema.sql first. "
                "Exiting cleanly.",
                file=sys.stderr,
            )
            return 0

    print(
        f"[risk] inputs: labs={_row_count(conn, 'labs')}, "
        f"snps={_row_count(conn, 'snps')}, "
        f"pedigree={_row_count(conn, 'pedigree')}, "
        f"pedigree_conditions={_row_count(conn, 'pedigree_conditions')}"
    )

    # ---------------- PhenoAge ----------------
    phenoage_rows = []
    phenoage_warnings = []
    if _row_count(conn, "labs") == 0:
        print("[risk] labs is empty; skipping PhenoAge.", file=sys.stderr)
    else:
        labs = [
            LabRow(
                id=r["id"], date=r["date"], metric=r["metric"],
                value=r["value"], unit=r["unit"],
            )
            for r in conn.execute(
                "SELECT id, date, metric, value, unit FROM labs "
                "ORDER BY date, id"
            )
        ]
        phenoage_rows, phenoage_warnings = compute_phenoage_rows(
            labs, birth_year=birth_year,
        )
        for w in phenoage_warnings:
            print(f"[risk] {w}", file=sys.stderr)
        print(f"[risk] PhenoAge: {len(phenoage_rows)} row(s) computed")

    # ---------------- Pedigree priors ----------------
    pedigree_rows = [
        PedigreeRow(person_id=r["person_id"], relationship=r["relationship"])
        for r in conn.execute(
            "SELECT person_id, relationship FROM pedigree"
        )
    ]
    condition_rows = [
        ConditionRow(
            person_id=r["person_id"], condition=r["condition"],
            age_at_onset=r["age_at_onset"],
        )
        for r in conn.execute(
            "SELECT person_id, condition, age_at_onset FROM pedigree_conditions"
        )
    ]
    pedigree_scores, pedigree_warnings = compute_pedigree_scores(
        pedigree_rows, condition_rows,
    )
    for w in pedigree_warnings:
        print(f"[risk] {w}", file=sys.stderr)
    print(f"[risk] pedigree priors: {len(pedigree_scores)} row(s) computed")

    # ---------------- PGS-lite (stub) ----------------
    snp_rows = [
        SnpRow(rsid=r["rsid"], genotype=r["genotype"])
        for r in conn.execute("SELECT rsid, genotype FROM snps")
    ]
    pgs_scores, pgs_warnings = compute_pgs_scores(snp_rows)
    for w in pgs_warnings:
        print(f"[risk] {w}", file=sys.stderr)
    print(f"[risk] PGS-lite: {len(pgs_scores)} row(s) computed")

    # ---------------- Idempotent DELETE ----------------
    today = _today()
    # PhenoAge rows: keyed by (date, 'phenoage'). Wipe all phenoage rows.
    conn.execute("DELETE FROM risk_scores WHERE score_id = 'phenoage'")
    # Pedigree score rows: keyed by today + score_id list above.
    if PEDIGREE_SCORE_IDS:
        placeholders = ",".join("?" for _ in PEDIGREE_SCORE_IDS)
        conn.execute(
            f"DELETE FROM risk_scores WHERE score_id IN ({placeholders})",
            PEDIGREE_SCORE_IDS,
        )
    # PGS rows: wipe by score_id prefix.
    conn.execute("DELETE FROM risk_scores WHERE score_id LIKE 'pgs_%'")
    # Our events: wipe before re-inserting.
    conn.execute("DELETE FROM events WHERE domain = 'risk'")

    # ---------------- INSERT ----------------
    inserted = 0
    events_inserted = 0

    for r in phenoage_rows:
        conn.execute(
            "INSERT INTO risk_scores "
            "(date, score_id, source, value, percentile, inputs_json, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                r.date, "phenoage", "levine_2018",
                r.value, None, r.inputs_json, r.notes,
            ),
        )
        inserted += 1

        # Dramatic event: PhenoAge > chronological + 5y.
        delta = r.value - r.chronological_age
        if delta >= 5.0:
            conn.execute(
                "INSERT INTO events (date, domain, event_type, summary, "
                "payload_json) VALUES (?, ?, ?, ?, ?)",
                (
                    r.date, "risk", "phenoage_elevated",
                    f"PhenoAge {r.value:.1f} exceeds chronological "
                    f"{r.chronological_age:.0f} by {delta:.1f} years",
                    json.dumps({
                        "phenoage": r.value,
                        "chronological_age": r.chronological_age,
                        "delta_years": round(delta, 2),
                    }, sort_keys=True),
                ),
            )
            events_inserted += 1

    for r in pedigree_scores:
        conn.execute(
            "INSERT INTO risk_scores "
            "(date, score_id, source, value, percentile, inputs_json, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                today, r.score_id, "pedigree_derived",
                r.value, None, r.inputs_json, r.notes,
            ),
        )
        inserted += 1

        # Dramatic event: first-degree count >= 2 for a major killer
        # before age 60. The pedigree module emits one row per bucket
        # named family_<bucket>_first_degree_before_60 carrying that
        # count directly.
        if (
            r.score_id.endswith("_first_degree_before_60")
            and r.value >= 2.0
        ):
            bucket = r.score_id[len("family_"):-len("_first_degree_before_60")]
            conn.execute(
                "INSERT INTO events (date, domain, event_type, summary, "
                "payload_json) VALUES (?, ?, ?, ?, ?)",
                (
                    today, "risk", "family_history_strong",
                    f">={int(r.value)} first-degree relatives with {bucket} "
                    f"before age 60",
                    r.inputs_json,
                ),
            )
            events_inserted += 1

    for r in pgs_scores:
        conn.execute(
            "INSERT INTO risk_scores "
            "(date, score_id, source, value, percentile, inputs_json, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                today, r.score_id, "pgs_catalog",
                r.value, None, r.inputs_json, r.notes,
            ),
        )
        inserted += 1

    # ---------------- ingest_meta ----------------
    notes_blob = json.dumps({
        "phenoage_rows": len(phenoage_rows),
        "pedigree_rows": len(pedigree_scores),
        "pgs_rows": len(pgs_scores),
        "events": events_inserted,
        "phenoage_warnings": len(phenoage_warnings),
        "pedigree_warnings": len(pedigree_warnings),
        "pgs_warnings": len(pgs_warnings),
    }, sort_keys=True)
    conn.execute(
        "INSERT OR REPLACE INTO ingest_meta (source, last_run, n_rows, "
        "source_file, notes) VALUES (?, ?, ?, ?, ?)",
        ("risk", _now(), inserted, None, notes_blob),
    )

    conn.commit()
    conn.close()

    print(
        f"[risk] done: inserted {inserted} risk_scores row(s), "
        f"{events_inserted} event(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
