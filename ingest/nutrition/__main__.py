"""Nutrition ingest entry point.

Run with: `python -m ingest.nutrition`

Reads every nutrition-shaped source under `w_data/`, aggregates to daily,
writes to `analysis/health.db.nutrition_daily`. Idempotent: deletes the
source's existing rows before inserting.

Also writes an `ingest_meta` row per source and appends `events` rows for
sustained (14-day) macro shifts >25% vs the trailing 90-day mean.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import pandas as pd

from . import parse_health_xlsx, parse_macrofactor

REPO_ROOT = Path(__file__).resolve().parents[2]
W_DATA = REPO_ROOT / "w_data"
DB_PATH = REPO_ROOT / "analysis" / "health.db"
SCHEMA_SQL = REPO_ROOT / "schema.sql"

# Files we explicitly handle. Anything else under w_data/ that looks
# nutrition-shaped goes into the "skipped" report at the end.
MACROFACTOR_GLOB = "MacroFactor-*.csv"
HEALTH_XLSX = W_DATA / "Health.xlsx"


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Apply schema.sql if any required tables are missing.

    schema.sql is owned by the schema agent; we just load it idempotently.
    """
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()


def _write_daily(
    conn: sqlite3.Connection, df: pd.DataFrame, source: str
) -> int:
    """Idempotent replace of all `nutrition_daily` rows for `source`."""
    conn.execute("DELETE FROM nutrition_daily WHERE source = ?", (source,))

    if df.empty:
        return 0

    cols = [
        "date",
        "kcal",
        "protein_g",
        "carb_g",
        "fat_g",
        "fiber_g",
        "sugar_g",
        "sodium_mg",
        "source",
        "source_file",
    ]
    # Cast numpy scalars to Python native so SQLite binds them as REAL/INTEGER
    # rather than BLOB. NaN -> None for proper SQL NULL.
    sub = df[cols].astype(object).where(pd.notna(df[cols]), None)
    rows = [tuple(r) for r in sub.itertuples(index=False, name=None)]

    conn.executemany(
        """
        INSERT INTO nutrition_daily
            (date, kcal, protein_g, carb_g, fat_g, fiber_g, sugar_g,
             sodium_mg, source, source_file)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def _write_ingest_meta(
    conn: sqlite3.Connection,
    source: str,
    n_rows: int,
    source_file: str | None,
    notes: str | None = None,
) -> None:
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
        (
            f"nutrition.{source}",
            dt.datetime.now().isoformat(timespec="seconds"),
            n_rows,
            source_file,
            notes,
        ),
    )


def _detect_macro_shift_events(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    """Append `events` rows for 14-day sustained macro shifts >25% vs trailing 90d mean.

    For each of kcal, protein_g, carb_g, fat_g: compute a rolling 14-day mean and a
    trailing-90-day baseline; flag the FIRST date on which the 14-day mean
    diverges from baseline by >25%. One event row per macro per shift.
    """
    if df.empty:
        return 0

    df = df.sort_values("date").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])

    macros = ["kcal", "protein_g", "carb_g", "fat_g"]
    inserted = 0

    # Idempotent: clear nutrition-shift events before re-inserting.
    conn.execute(
        "DELETE FROM events WHERE domain = 'nutrition' AND event_type = 'macro_shift_14d'"
    )

    for macro in macros:
        s = pd.to_numeric(df[macro], errors="coerce")
        if s.dropna().empty:
            continue

        # min_periods so we don't fire on the warmup window.
        roll14 = s.rolling(window=14, min_periods=14).mean()
        base90 = s.rolling(window=90, min_periods=30).mean().shift(14)

        ratio = (roll14 - base90) / base90
        flagged = ratio.abs() > 0.25

        # Take the first index in any consecutive flagged run.
        prev = False
        for i, hit in enumerate(flagged.fillna(False)):
            if hit and not prev:
                date_str = df.loc[i, "date"].strftime("%Y-%m-%d")
                payload = {
                    "macro": macro,
                    "rolling_14d_mean": float(roll14.iloc[i]),
                    "trailing_90d_mean": float(base90.iloc[i]),
                    "pct_change": float(ratio.iloc[i]),
                }
                summary = (
                    f"{macro} 14d mean shifted "
                    f"{ratio.iloc[i] * 100:+.1f}% vs trailing 90d baseline"
                )
                conn.execute(
                    """
                    INSERT INTO events (date, domain, event_type, summary, payload_json)
                    VALUES (?, 'nutrition', 'macro_shift_14d', ?, ?)
                    """,
                    (date_str, summary, json.dumps(payload)),
                )
                inserted += 1
            prev = hit

    return inserted


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_schema(conn)

    total_rows = 0
    all_daily: list[pd.DataFrame] = []
    skipped: list[tuple[str, str]] = []

    # --- MacroFactor CSV(s) ----------------------------------------------
    mf_files = sorted(W_DATA.glob(MACROFACTOR_GLOB))
    if not mf_files:
        skipped.append((MACROFACTOR_GLOB, "no matching files in w_data/"))
    for mf_path in mf_files:
        print(f"parsing {mf_path.name}...")
        df = parse_macrofactor.parse(mf_path)
        n = _write_daily(conn, df, parse_macrofactor.SOURCE)
        _write_ingest_meta(
            conn,
            source=parse_macrofactor.SOURCE,
            n_rows=n,
            source_file=mf_path.name,
        )
        print(f"  -> {n} daily rows into nutrition_daily")
        total_rows += n
        all_daily.append(df)

    # --- Health.xlsx ------------------------------------------------------
    if HEALTH_XLSX.exists():
        print(f"parsing {HEALTH_XLSX.name}...")
        df = parse_health_xlsx.parse(HEALTH_XLSX)
        n = _write_daily(conn, df, parse_health_xlsx.SOURCE)
        if n == 0:
            skipped.append(
                (
                    HEALTH_XLSX.name,
                    "no nutrition-shaped sheets (other sheets owned by other agents)",
                )
            )
        else:
            all_daily.append(df)
            total_rows += n
        _write_ingest_meta(
            conn,
            source=parse_health_xlsx.SOURCE,
            n_rows=n,
            source_file=HEALTH_XLSX.name,
            notes="no nutrition sheets present" if n == 0 else None,
        )
        print(f"  -> {n} daily rows into nutrition_daily")
    else:
        skipped.append((HEALTH_XLSX.name, "file not present in w_data/"))

    # --- Events -----------------------------------------------------------
    if all_daily:
        combined = pd.concat(all_daily, ignore_index=True)
        # Aggregate across sources per day for event detection (one signal,
        # not per-source). Take mean across sources if multiple log the
        # same date; usually only one source per day.
        per_day = (
            combined.groupby("date", as_index=False)[
                ["kcal", "protein_g", "carb_g", "fat_g"]
            ]
            .mean(numeric_only=True)
        )
        n_events = _detect_macro_shift_events(conn, per_day)
        print(f"detected {n_events} nutrition macro_shift_14d event(s)")

    conn.commit()
    conn.close()

    print(f"\nnutrition ingest complete: {total_rows} total daily rows written")
    if skipped:
        print("skipped files:")
        for name, reason in skipped:
            print(f"  - {name}: {reason}")


if __name__ == "__main__":
    main()
