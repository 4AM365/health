"""
db.py — open analysis/health.db read-only and provide table-aware helpers
that degrade gracefully when the DB or specific tables don't exist yet.

Per docs/UI_STRUCTURE.md: dashboard NEVER writes to the bus. Read-only mode
is enforced via the `mode=ro` URI param. The calculators loader is the one
exception — it writes to nutrient_targets via a separate read-write opener
(see app/synthesis/calculators.py).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "analysis" / "health.db"


def db_exists() -> bool:
    return DB_PATH.exists()


def open_ro() -> Optional[sqlite3.Connection]:
    """Open health.db read-only. Returns None if the DB doesn't exist yet."""
    if not DB_PATH.exists():
        return None
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def open_rw() -> sqlite3.Connection:
    """Open read-write — used ONLY by the calculators synthesis layer to
    write nutrient_targets. Creates analysis/ if needed but does not create
    the DB itself; if the schema isn't loaded, callers see a clear sqlite
    error."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    cur = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return cur.fetchone() is not None


def read_sql_safe(query: str, params: tuple = ()) -> pd.DataFrame:
    """Run a SELECT and return a DataFrame, or empty DataFrame if the DB or
    tables don't exist. Catches OperationalError so views can render empty
    states without crashing."""
    con = open_ro()
    if con is None:
        return pd.DataFrame()
    try:
        return pd.read_sql_query(query, con, params=params)
    except (sqlite3.OperationalError, pd.errors.DatabaseError):
        return pd.DataFrame()
    finally:
        con.close()


def ingest_meta() -> pd.DataFrame:
    """Returns the ingest_meta table, or empty DataFrame."""
    return read_sql_safe("SELECT source, last_run, n_rows, source_file, notes FROM ingest_meta")
