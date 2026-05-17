"""body agent entry point: parse DEXA / lifts / sleep / Health.xlsx and
populate `body_comp`, `lifts`, `sleep`, `events`, `ingest_meta` in health.db.

Idempotent: each run does `DELETE FROM <my tables>; INSERT ...`. We never
append-with-dupes. Schema is owned by the schema agent (schema.sql);
this module only reads other domains' tables — never writes them.

Usage:
    python -m ingest.body
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from ingest.body.parse_dexa import parse_dexa
from ingest.body.parse_health_xlsx import parse_health_xlsx
from ingest.body.parse_lifts import parse_lifts
from ingest.body.parse_sleep import parse_sleep, skip_csv_and_pngs

REPO_ROOT = Path(__file__).resolve().parents[2]
W_DATA = REPO_ROOT / "w_data"
DB_PATH = REPO_ROOT / "analysis" / "health.db"
SCHEMA_PATH = REPO_ROOT / "schema.sql"

DEXA_PDF = W_DATA / "William Craig 3-3-22 Dexa Body Composition Report v2024.pdf"
LIFTS_XLSX = W_DATA / "2025 Lifts.xlsx"
SLEEP_XLSX = W_DATA / "Sleep_Processed.xlsx"
HEALTH_XLSX = W_DATA / "Health.xlsx"


def _ensure_db(con: sqlite3.Connection) -> None:
    """Apply schema.sql if any of our tables are missing.

    The schema agent is the canonical owner of schema.sql; we never modify it.
    """
    cur = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('body_comp','lifts','sleep','events','ingest_meta')"
    )
    have = {r[0] for r in cur.fetchall()}
    needed = {"body_comp", "lifts", "sleep", "events", "ingest_meta"}
    if needed.issubset(have):
        return
    con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def _merge_body_comp(rows: list[dict]) -> list[dict]:
    """body_comp has a single-column PK on `date`. The DEXA PDF and the
    Health.xlsx Bloodwork sheet can both have a 2024-10-04 / 2025-10-03 row,
    so we merge per-date, letting later sources fill NULLs in earlier ones.

    Precedence: the actual DEXA PDF beats the Health.xlsx hand-typed copy on
    any column that's non-NULL in the PDF. We trust the report.
    """
    by_date: dict[str, dict] = {}
    for r in rows:
        d = r["date"]
        if d not in by_date:
            by_date[d] = dict(r)
            continue
        # Merge: keep first non-NULL per column; concatenate source_file.
        existing = by_date[d]
        for k, v in r.items():
            if k == "source_file":
                if v and v not in existing.get("source_file", ""):
                    existing["source_file"] = (
                        f"{existing['source_file']};{v}"
                        if existing.get("source_file") else v
                    )
            elif existing.get(k) is None and v is not None:
                existing[k] = v
    return list(by_date.values())


def _emit_events(body_comp: list[dict], lifts: list[dict], sleep_rows: list[dict]) -> list[tuple]:
    """Notable events:
      - body comp: >2 percentage-point shift in bf_pct between consecutive scans
      - lifts: new e1RM PR per lift
      - sleep: >7 consecutive weekly summaries with total_hr < 6
    """
    events: list[tuple] = []  # (date, domain, event_type, summary, payload_json)

    # --- body comp shifts
    bc_sorted = sorted(
        (r for r in body_comp if r.get("bf_pct") is not None),
        key=lambda r: r["date"],
    )
    for prev, cur in zip(bc_sorted, bc_sorted[1:]):
        delta = cur["bf_pct"] - prev["bf_pct"]
        if abs(delta) > 2.0:
            events.append(
                (
                    cur["date"],
                    "body",
                    "bf_pct_shift",
                    f"body fat {delta:+.1f}pp vs {prev['date']} "
                    f"({prev['bf_pct']:.1f}% to {cur['bf_pct']:.1f}%)",
                    json.dumps({"prev_date": prev["date"], "prev_bf_pct": prev["bf_pct"],
                                 "bf_pct": cur["bf_pct"], "delta_pp": round(delta, 2)}),
                )
            )

    # --- lift PRs (e1RM)
    best_so_far: dict[str, float] = {}
    for r in sorted(lifts, key=lambda x: x["date"]):
        lift = r["lift"]
        e1rm = r.get("e1rm")
        if e1rm is None:
            continue
        prior = best_so_far.get(lift)
        if prior is None or e1rm > prior + 1e-6:
            # Only fire as an event once we have a prior baseline.
            if prior is not None:
                events.append(
                    (
                        r["date"],
                        "body",
                        "lift_pr",
                        f"{lift} e1RM PR {e1rm:.1f}kg (prev {prior:.1f}kg)",
                        json.dumps({
                            "lift": lift, "e1rm_kg": e1rm, "prev_e1rm_kg": prior,
                            "weight_kg": r["weight_kg"], "reps": r["reps"],
                        }),
                    )
                )
            best_so_far[lift] = e1rm

    # --- sleep streaks of <6h totals across consecutive weekly rows
    sl_sorted = sorted(sleep_rows, key=lambda r: r["date"])
    streak: list[dict] = []
    for r in sl_sorted:
        if r.get("total_hr") is not None and r["total_hr"] < 6.0:
            streak.append(r)
            continue
        if len(streak) > 7:
            events.append(
                (
                    streak[-1]["date"],
                    "sleep",
                    "low_sleep_streak",
                    f"{len(streak)} consecutive weekly summaries <6h "
                    f"({streak[0]['date']} - {streak[-1]['date']})",
                    json.dumps({
                        "start": streak[0]["date"], "end": streak[-1]["date"],
                        "weeks": len(streak),
                    }),
                )
            )
        streak = []
    if len(streak) > 7:
        events.append(
            (
                streak[-1]["date"], "sleep", "low_sleep_streak",
                f"{len(streak)} consecutive weekly summaries <6h "
                f"({streak[0]['date']} - {streak[-1]['date']})",
                json.dumps({
                    "start": streak[0]["date"], "end": streak[-1]["date"],
                    "weeks": len(streak),
                }),
            )
        )
    return events


def _write(con: sqlite3.Connection,
            body_comp: list[dict],
            lifts: list[dict],
            sleep_rows: list[dict],
            events: list[tuple],
            meta: list[tuple]) -> None:
    """Idempotent writes: delete-then-insert per owned table; targeted
    delete of body-domain rows in the shared `events` table.
    """
    con.execute("DELETE FROM body_comp")
    con.execute("DELETE FROM lifts")
    con.execute("DELETE FROM sleep")
    con.execute("DELETE FROM events WHERE domain IN ('body','sleep')")

    con.executemany(
        "INSERT INTO body_comp (date, bf_pct, lbm_kg, fat_mass_kg, vat_g, bmd, source_file) "
        "VALUES (:date, :bf_pct, :lbm_kg, :fat_mass_kg, :vat_g, :bmd, :source_file)",
        body_comp,
    )
    con.executemany(
        "INSERT INTO lifts (date, lift, weight_kg, reps, sets, e1rm, source_file) "
        "VALUES (:date, :lift, :weight_kg, :reps, :sets, :e1rm, :source_file)",
        lifts,
    )
    con.executemany(
        "INSERT INTO sleep (date, total_hr, rem_hr, deep_hr, light_hr, awake_hr, hr_avg, source) "
        "VALUES (:date, :total_hr, :rem_hr, :deep_hr, :light_hr, :awake_hr, :hr_avg, :source)",
        sleep_rows,
    )
    con.executemany(
        "INSERT INTO events (date, domain, event_type, summary, payload_json) "
        "VALUES (?, ?, ?, ?, ?)",
        events,
    )

    # ingest_meta: one row per source we processed (idempotent upsert).
    for source, last_run, n_rows, source_file, notes in meta:
        con.execute(
            "INSERT INTO ingest_meta (source, last_run, n_rows, source_file, notes) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(source) DO UPDATE SET "
            "  last_run=excluded.last_run, "
            "  n_rows=excluded.n_rows, "
            "  source_file=excluded.source_file, "
            "  notes=excluded.notes",
            (source, last_run, n_rows, source_file, notes),
        )


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SCHEMA_PATH.exists():
        raise SystemExit(f"[body] FAIL: schema.sql not found at {SCHEMA_PATH}")

    # Parse each source. Fail loud if a configured source is missing.
    sources_missing: list[str] = []
    for p in (DEXA_PDF, LIFTS_XLSX, SLEEP_XLSX, HEALTH_XLSX):
        if not p.exists():
            sources_missing.append(p.name)
    if sources_missing:
        print(f"[body] WARN: missing source files: {sources_missing}")

    dexa_rows = parse_dexa(DEXA_PDF) if DEXA_PDF.exists() else []
    health_rows = parse_health_xlsx(HEALTH_XLSX) if HEALTH_XLSX.exists() else []
    body_comp = _merge_body_comp(dexa_rows + health_rows)
    print(f"[body] body_comp: {len(body_comp)} rows "
          f"(dexa pdf={len(dexa_rows)}, health.xlsx={len(health_rows)})")

    lifts = parse_lifts(LIFTS_XLSX) if LIFTS_XLSX.exists() else []
    print(f"[body] lifts: {len(lifts)} rows")

    sleep_rows = parse_sleep(SLEEP_XLSX) if SLEEP_XLSX.exists() else []
    sleep_skipped = skip_csv_and_pngs(W_DATA)
    print(f"[body] sleep: {len(sleep_rows)} rows; "
          f"skipped {len(sleep_skipped)} non-parseable sources")

    events = _emit_events(body_comp, lifts, sleep_rows)
    print(f"[body] events: {len(events)} body/sleep events")

    now = datetime.now().isoformat(timespec="seconds")
    meta: list[tuple] = [
        ("body:dexa", now, len(dexa_rows), DEXA_PDF.name,
         "DEXA report; BMD column holds T-score (no g/cm^2 in source)"),
        ("body:health_xlsx", now, len(health_rows), HEALTH_XLSX.name,
         "Bodyweight + DEXA rows from Bloodwork sheet only; other sheets skipped"),
        ("body:lifts", now, len(lifts), LIFTS_XLSX.name,
         "Strength log; e1RM via Epley; weights converted lbs→kg"),
        ("body:sleep", now, len(sleep_rows), SLEEP_XLSX.name,
         f"Weekly aggregates; CSV + {sum(1 for s in sleep_skipped if s.endswith('.png'))} png images skipped"),
    ]

    with sqlite3.connect(DB_PATH) as con:
        _ensure_db(con)
        _write(con, body_comp, lifts, sleep_rows, events, meta)
        con.commit()

    print(f"[body] done -> {DB_PATH}")


if __name__ == "__main__":
    main()
