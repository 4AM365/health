"""Bloodwork ingest entry point.

Run from the repo root:

    python -m ingest.bloodwork

Loads (or initializes) `analysis/health.db` from `schema.sql`, then parses
every recognized bloodwork file under `w_data/`, normalizes metrics + units,
and writes idempotent `DELETE + INSERT` batches into `labs`. Also emits one
row per source file into `ingest_meta`, plus one `events` row for every
notable reading (out-of-range or >25% delta vs trailing 90-day mean).

Fails loud: every skipped file or row is printed with its reason.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import asdict
from datetime import datetime, date
from pathlib import Path

from ingest.bloodwork.parse_csv import (
    parse_bloodwork_csv,
    explain_blood_test_results_csv,
)
from ingest.bloodwork.parse_pdf import parse_spectracell_pdf


REPO_ROOT = Path(__file__).resolve().parents[2]
W_DATA = REPO_ROOT / "w_data"
ANALYSIS = REPO_ROOT / "analysis"
DB_PATH = ANALYSIS / "health.db"
SCHEMA_PATH = REPO_ROOT / "schema.sql"


# --- file dispatch ---------------------------------------------------------

CSV_FILES = ["bloodwork.csv"]
PDF_FILES = ["Craig,William10212025.pdf", "2025.pdf", "-279-00022-241005.pdf"]
KNOWN_NO_DATE_CSV = ["Blood_Test_Results.csv"]


def _ensure_db() -> sqlite3.Connection:
    ANALYSIS.mkdir(parents=True, exist_ok=True)
    is_fresh = not DB_PATH.exists()
    conn = sqlite3.connect(DB_PATH)
    if is_fresh:
        with SCHEMA_PATH.open("r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
    # Always make sure required tables exist (cheap; schema.sql uses IF NOT EXISTS).
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    return conn


def _clear_old_rows(conn: sqlite3.Connection, source_files: list[str]) -> None:
    """Idempotency: drop everything we previously inserted for these files."""
    if not source_files:
        return
    placeholders = ",".join("?" * len(source_files))
    conn.execute(f"DELETE FROM labs WHERE source_file IN ({placeholders})", source_files)
    conn.execute(
        f"DELETE FROM events WHERE domain = 'bloodwork' AND json_extract(payload_json, '$.source_file') IN ({placeholders})",
        source_files,
    )
    conn.commit()


def _insert_labs(conn: sqlite3.Connection, rows) -> int:
    if not rows:
        return 0
    payload = [
        (
            r.date, r.metric, r.value, r.unit,
            r.ref_low, r.ref_high, r.source_file, r.lab_provider, r.notes,
        )
        for r in rows
    ]
    conn.executemany(
        """
        INSERT INTO labs (date, metric, value, unit, ref_low, ref_high, source_file, lab_provider, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    conn.commit()
    return len(payload)


# --- event detection -------------------------------------------------------

def _detect_events(conn: sqlite3.Connection, new_rows) -> list[tuple]:
    """Return events to INSERT.

    Two triggers per AGENTS.md / the bloodwork brief:
      - lab_oor   : value crosses ref_low/ref_high
      - lab_delta : >25% absolute change vs trailing 90-day mean for the same metric
    """
    events: list[tuple] = []

    # Group new rows by metric to compute trailing means using prior history
    # already in `labs` (excluding the rows we just inserted; we rely on the
    # caller having committed before calling this).
    by_metric: dict[str, list] = {}
    for r in new_rows:
        by_metric.setdefault(r.metric, []).append(r)

    for metric, rows in by_metric.items():
        for r in rows:
            # OOR check
            if r.ref_low is not None and r.value < r.ref_low:
                events.append((
                    r.date, "bloodwork", "lab_event",
                    f"{metric} {r.value}{r.unit or ''} below ref_low {r.ref_low}",
                    json.dumps({"kind": "oor_low", "metric": metric, "value": r.value,
                                "unit": r.unit, "ref_low": r.ref_low, "source_file": r.source_file}),
                ))
            if r.ref_high is not None and r.value > r.ref_high:
                events.append((
                    r.date, "bloodwork", "lab_event",
                    f"{metric} {r.value}{r.unit or ''} above ref_high {r.ref_high}",
                    json.dumps({"kind": "oor_high", "metric": metric, "value": r.value,
                                "unit": r.unit, "ref_high": r.ref_high, "source_file": r.source_file}),
                ))

            # Delta vs trailing 90d mean
            cur = conn.execute(
                """
                SELECT AVG(value) FROM labs
                WHERE metric = ?
                  AND date < ?
                  AND date >= date(?, '-90 days')
                  AND value IS NOT NULL
                """,
                (metric, r.date, r.date),
            )
            (mean,) = cur.fetchone() or (None,)
            if mean is not None and mean != 0:
                delta = abs(r.value - mean) / abs(mean)
                if delta > 0.25:
                    events.append((
                        r.date, "bloodwork", "lab_event",
                        f"{metric} changed {delta*100:.0f}% vs 90d mean ({r.value} vs {mean:.2f})",
                        json.dumps({"kind": "delta_90d", "metric": metric, "value": r.value,
                                    "mean_90d": mean, "delta_pct": delta,
                                    "source_file": r.source_file}),
                    ))
    return events


def _insert_events(conn: sqlite3.Connection, events: list[tuple]) -> int:
    if not events:
        return 0
    conn.executemany(
        """
        INSERT INTO events (date, domain, event_type, summary, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        events,
    )
    conn.commit()
    return len(events)


def _write_ingest_meta(conn: sqlite3.Connection, source: str, n_rows: int,
                       source_file: str | None, notes: str | None) -> None:
    conn.execute(
        """
        INSERT INTO ingest_meta (source, last_run, n_rows, source_file, notes)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source) DO UPDATE SET
            last_run = excluded.last_run,
            n_rows = excluded.n_rows,
            source_file = excluded.source_file,
            notes = excluded.notes
        """,
        (source, datetime.now().isoformat(timespec="seconds"), n_rows, source_file, notes),
    )
    conn.commit()


# --- main ------------------------------------------------------------------

def main() -> int:
    print(f"bloodwork ingest  ->  {DB_PATH}")
    conn = _ensure_db()

    all_source_files: list[str] = []
    all_rows: list = []
    all_skips: list[tuple[str, str, str]] = []   # (file, label, reason)
    file_skips: list[tuple[str, str]] = []       # (file, reason)

    # --- CSV: bloodwork.csv ------------------------------------------------
    for name in CSV_FILES:
        p = W_DATA / name
        if not p.exists():
            file_skips.append((name, "file not found in w_data/"))
            continue
        result = parse_bloodwork_csv(p)
        all_source_files.append(name)
        all_rows.extend(result.rows)
        for label, reason in result.skipped_labels:
            all_skips.append((name, label, reason))
        for d, label, raw in result.skipped_values:
            all_skips.append((name, f"{label} @ {d}", f"non-numeric value: {raw!r}"))
        print(f"  parsed {name}: {len(result.rows)} rows, "
              f"{len(result.skipped_labels)} label-skips, "
              f"{len(result.skipped_values)} value-skips")

    # --- CSV: Blood_Test_Results.csv (no-date, intentionally skipped) ------
    for name in KNOWN_NO_DATE_CSV:
        p = W_DATA / name
        if p.exists():
            reason = explain_blood_test_results_csv(p)
            file_skips.append((name, reason))

    # --- PDFs --------------------------------------------------------------
    for name in PDF_FILES:
        p = W_DATA / name
        if not p.exists():
            file_skips.append((name, "file not found in w_data/"))
            continue
        result = parse_spectracell_pdf(p)
        if result.skip_file_reason:
            file_skips.append((name, result.skip_file_reason))
            print(f"  skipped {name}: {result.skip_file_reason}")
            continue
        all_source_files.append(name)
        all_rows.extend(result.rows)
        for label, reason in result.skipped_labels:
            all_skips.append((name, label, reason))
        print(f"  parsed {name}: {len(result.rows)} rows, "
              f"{len(result.skipped_labels)} label-skips")

    # --- Idempotent write --------------------------------------------------
    _clear_old_rows(conn, all_source_files)
    n_inserted = _insert_labs(conn, all_rows)
    events = _detect_events(conn, all_rows)
    n_events = _insert_events(conn, events)

    # --- ingest_meta -------------------------------------------------------
    for sf in all_source_files:
        n = sum(1 for r in all_rows if r.source_file == sf)
        _write_ingest_meta(
            conn,
            source=f"bloodwork:{sf}",
            n_rows=n,
            source_file=sf,
            notes=None,
        )
    # Aggregate row
    _write_ingest_meta(
        conn,
        source="bloodwork",
        n_rows=n_inserted,
        source_file=", ".join(all_source_files) if all_source_files else None,
        notes=f"events={n_events}; skipped_files={len(file_skips)}",
    )

    # --- Report ------------------------------------------------------------
    print("---")
    print(f"INSERTED: {n_inserted} labs, {n_events} events")
    print(f"FILES INGESTED: {len(all_source_files)}")
    for sf in all_source_files:
        n = sum(1 for r in all_rows if r.source_file == sf)
        print(f"  - {sf}: {n} rows")
    if file_skips:
        print(f"FILES SKIPPED: {len(file_skips)}")
        for name, reason in file_skips:
            print(f"  - {name}: {reason}")
    if all_skips:
        print(f"LABEL/VALUE SKIPS: {len(all_skips)}")
        # Deduplicate by (label, reason) to keep output sane
        seen: dict[tuple[str, str], int] = {}
        for f, label, reason in all_skips:
            key = (label, reason)
            seen[key] = seen.get(key, 0) + 1
        for (label, reason), n in sorted(seen.items()):
            print(f"  - [{n}x] {label}  ->  {reason}")

    # --- Verification ------------------------------------------------------
    if not all_source_files:
        print("ERROR: no files were ingested.", file=sys.stderr)
        return 1
    for sf in all_source_files:
        n = sum(1 for r in all_rows if r.source_file == sf)
        if n == 0:
            print(f"ERROR: source file {sf} produced zero rows.", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
