"""
tools.py — read-only tool registry per docs/LLM_INTERFACE.md §3.

Each tool:
- Takes JSON-safe args.
- Returns a JSON-safe dict (so the agent loop can stringify it for the API).
- Caps results at MAX_ROWS (W7 mitigation) and includes truncated:true flag.
- Never returns rows joined against `snps` or `pedigree*`.

EXPLICITLY ABSENT (privacy):
- get_snps, get_pedigree, run_sql, read_file
- get_traits joins only `traits` — never `snps`.

Tool calls log to analysis/llm_audit.jsonl (gitignored) — audit trail per §3.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from app.db import open_ro, read_sql_safe

MAX_ROWS = 500
AUDIT_LOG = Path(__file__).parent.parent.parent / "analysis" / "llm_audit.jsonl"


def _truncate(rows: list[dict]) -> dict:
    truncated = len(rows) > MAX_ROWS
    return {"rows": rows[:MAX_ROWS], "truncated": truncated, "n_total": len(rows)}


def _audit(tool: str, args: dict, n_rows: int) -> None:
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "tool": tool,
                        "args": args,
                        "n_rows_returned": n_rows,
                    }
                )
                + "\n"
            )
    except OSError:
        # Audit failure must not break the tool — surface in stderr later.
        pass


# ---------------------------------------------------------------------- tools


def list_metrics() -> dict:
    df = read_sql_safe(
        """
        SELECT metric, unit,
               COUNT(*) AS n_observations,
               MIN(date) AS first_date,
               MAX(date) AS last_date
        FROM labs
        GROUP BY metric, unit
        ORDER BY metric
        """
    )
    rows = df.to_dict(orient="records")
    _audit("list_metrics", {}, len(rows))
    return _truncate(rows)


def get_lab_series(metric: str, since: str | None = None, until: str | None = None) -> dict:
    q = "SELECT date, value, ref_low, ref_high FROM labs WHERE metric = ?"
    params: list = [metric]
    if since:
        q += " AND date >= ?"
        params.append(since)
    if until:
        q += " AND date <= ?"
        params.append(until)
    q += " ORDER BY date"
    df = read_sql_safe(q, tuple(params))
    rows = df.to_dict(orient="records")
    _audit("get_lab_series", {"metric": metric, "since": since, "until": until}, len(rows))
    return _truncate(rows)


def get_lab_window_summary(metric: str, days: int = 90) -> dict:
    q = """
    SELECT date, value, ref_low, ref_high
    FROM labs
    WHERE metric = ? AND date >= date('now', ?)
    ORDER BY date
    """
    df = read_sql_safe(q, (metric, f"-{int(days)} days"))
    if df.empty:
        out = {"metric": metric, "days": days, "n": 0}
    else:
        last = df["value"].iloc[-1]
        first = df["value"].iloc[0]
        delta_pct = (
            (last - first) / first * 100.0 if first not in (0, None) and not math.isnan(first) else None
        )
        in_range = df.dropna(subset=["value"])
        if not in_range.empty and "ref_low" in df and "ref_high" in df:
            within = in_range.apply(
                lambda r: (
                    (r["ref_low"] is None or r["value"] >= r["ref_low"])
                    and (r["ref_high"] is None or r["value"] <= r["ref_high"])
                ),
                axis=1,
            )
            in_range_pct = float(within.mean() * 100.0)
        else:
            in_range_pct = None
        out = {
            "metric": metric,
            "days": days,
            "n": int(len(df)),
            "min": float(df["value"].min()) if not df.empty else None,
            "max": float(df["value"].max()) if not df.empty else None,
            "mean": float(df["value"].mean()) if not df.empty else None,
            "last": float(last) if last is not None else None,
            "first": float(first) if first is not None else None,
            "delta_pct": delta_pct,
            "in_range_pct": in_range_pct,
        }
    _audit("get_lab_window_summary", {"metric": metric, "days": days}, out.get("n", 0))
    return out


def get_nutrition_window(days: int = 30, group_by: str = "day") -> dict:
    q = """
    SELECT date, kcal, protein_g, carb_g, fat_g, fiber_g, sugar_g, sodium_mg, source
    FROM nutrition_daily
    WHERE date >= date('now', ?)
    ORDER BY date
    """
    df = read_sql_safe(q, (f"-{int(days)} days",))
    rows = df.to_dict(orient="records")
    _audit("get_nutrition_window", {"days": days, "group_by": group_by}, len(rows))
    return _truncate(rows)


def get_body_composition(since: str | None = None) -> dict:
    q = "SELECT date, bf_pct, lbm_kg, fat_mass_kg, vat_g, bmd FROM body_comp"
    params: tuple = ()
    if since:
        q += " WHERE date >= ?"
        params = (since,)
    q += " ORDER BY date"
    df = read_sql_safe(q, params)
    rows = df.to_dict(orient="records")
    _audit("get_body_composition", {"since": since}, len(rows))
    return _truncate(rows)


def get_lift_prs(lift: str | None = None) -> dict:
    if lift:
        q = """
        SELECT date, lift, MAX(e1rm) AS e1rm
        FROM lifts WHERE lift = ?
        GROUP BY date, lift ORDER BY date
        """
        df = read_sql_safe(q, (lift,))
    else:
        q = """
        SELECT date, lift, MAX(e1rm) AS e1rm
        FROM lifts GROUP BY date, lift ORDER BY date
        """
        df = read_sql_safe(q)
    rows = df.to_dict(orient="records")
    _audit("get_lift_prs", {"lift": lift}, len(rows))
    return _truncate(rows)


def get_sleep_window(days: int = 30) -> dict:
    q = """
    SELECT date, total_hr, rem_hr, deep_hr, light_hr, awake_hr, hr_avg, source
    FROM sleep
    WHERE date >= date('now', ?)
    ORDER BY date
    """
    df = read_sql_safe(q, (f"-{int(days)} days",))
    rows = df.to_dict(orient="records")
    _audit("get_sleep_window", {"days": days}, len(rows))
    return _truncate(rows)


def get_traits(category: str | None = None) -> dict:
    """Derived traits ONLY. Does NOT join to snps or pedigree."""
    if category:
        q = """
        SELECT trait, category, value, source, confidence, notes
        FROM traits WHERE category = ? ORDER BY trait
        """
        df = read_sql_safe(q, (category,))
    else:
        q = """
        SELECT trait, category, value, source, confidence, notes
        FROM traits ORDER BY category, trait
        """
        df = read_sql_safe(q)
    rows = df.to_dict(orient="records")
    _audit("get_traits", {"category": category}, len(rows))
    return _truncate(rows)


def get_events(since: str | None = None, until: str | None = None) -> dict:
    """Returns `summary` only — `payload_json` is stripped per LLM_INTERFACE §3."""
    q = "SELECT date, domain, event_type, summary FROM events"
    clauses: list[str] = []
    params: list = []
    if since:
        clauses.append("date >= ?")
        params.append(since)
    if until:
        clauses.append("date <= ?")
        params.append(until)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY date"
    df = read_sql_safe(q, tuple(params))
    rows = df.to_dict(orient="records")
    _audit("get_events", {"since": since, "until": until}, len(rows))
    return _truncate(rows)


def correlate(metric_a: str, metric_b: str, window_days: int = 365) -> dict:
    """Pearson r over the last `window_days`. metric_b can be a nutrition
    column (kcal/protein_g/carb_g/fat_g/fiber_g/sugar_g/sodium_mg) or a lab
    metric. Computed deterministically; LLM only interprets."""
    # Try labs A
    a = read_sql_safe(
        "SELECT date, value FROM labs WHERE metric = ? AND date >= date('now', ?) ORDER BY date",
        (metric_a, f"-{int(window_days)} days"),
    )
    if a.empty:
        _audit("correlate", {"metric_a": metric_a, "metric_b": metric_b}, 0)
        return {"r": None, "n": 0, "note": f"no rows for {metric_a}"}

    a = a.rename(columns={"value": "a"})

    NUTRI_COLS = {"kcal", "protein_g", "carb_g", "fat_g", "fiber_g", "sugar_g", "sodium_mg"}
    if metric_b in NUTRI_COLS:
        b = read_sql_safe(
            f"SELECT date, {metric_b} AS b FROM nutrition_daily WHERE date >= date('now', ?) ORDER BY date",
            (f"-{int(window_days)} days",),
        )
    else:
        b = read_sql_safe(
            "SELECT date, value AS b FROM labs WHERE metric = ? AND date >= date('now', ?) ORDER BY date",
            (metric_b, f"-{int(window_days)} days"),
        )

    if b.empty:
        _audit("correlate", {"metric_a": metric_a, "metric_b": metric_b}, 0)
        return {"r": None, "n": 0, "note": f"no rows for {metric_b}"}

    merged = pd.merge(a, b, on="date", how="inner").dropna()
    if len(merged) < 3:
        _audit("correlate", {"metric_a": metric_a, "metric_b": metric_b}, len(merged))
        return {"r": None, "n": len(merged), "note": "n<3"}

    r = float(merged["a"].corr(merged["b"]))
    pairs = merged.tail(MAX_ROWS).to_dict(orient="records")
    _audit("correlate", {"metric_a": metric_a, "metric_b": metric_b}, len(merged))
    return {
        "r": r,
        "n": int(len(merged)),
        "window_days": int(window_days),
        "metric_a": metric_a,
        "metric_b": metric_b,
        "pairs": pairs,
        "truncated": len(merged) > MAX_ROWS,
    }


# ---------------------------------------------------------------------- registry

# Anthropic tool-use schema. Strict per-tool.
TOOL_SCHEMAS: list[dict] = [
    {
        "name": "list_metrics",
        "description": "List all lab metrics available with units and date ranges.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_lab_series",
        "description": "Time series of a single lab metric. Supports optional date bounds (YYYY-MM-DD).",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string"},
                "since":  {"type": "string", "description": "ISO date lower bound"},
                "until":  {"type": "string", "description": "ISO date upper bound"},
            },
            "required": ["metric"],
        },
    },
    {
        "name": "get_lab_window_summary",
        "description": "Min/max/mean/last/delta_pct for a lab metric over the last N days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string"},
                "days":   {"type": "integer", "default": 90},
            },
            "required": ["metric"],
        },
    },
    {
        "name": "get_nutrition_window",
        "description": "Daily macros and calories over the last N days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days":     {"type": "integer", "default": 30},
                "group_by": {"type": "string", "enum": ["day", "week", "month"], "default": "day"},
            },
            "required": [],
        },
    },
    {
        "name": "get_body_composition",
        "description": "DEXA snapshots since an optional ISO date.",
        "input_schema": {
            "type": "object",
            "properties": {"since": {"type": "string"}},
            "required": [],
        },
    },
    {
        "name": "get_lift_prs",
        "description": "Estimated 1RM trend, optionally filtered to one lift.",
        "input_schema": {
            "type": "object",
            "properties": {"lift": {"type": "string"}},
            "required": [],
        },
    },
    {
        "name": "get_sleep_window",
        "description": "Sleep duration and stages over the last N days.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "default": 30}},
            "required": [],
        },
    },
    {
        "name": "get_traits",
        "description": "Derived genome traits (NEVER raw rsids or genotypes). Filter by category if given.",
        "input_schema": {
            "type": "object",
            "properties": {"category": {"type": "string"}},
            "required": [],
        },
    },
    {
        "name": "get_events",
        "description": "Cross-domain timeline events. summary only (payload stripped).",
        "input_schema": {
            "type": "object",
            "properties": {
                "since": {"type": "string"},
                "until": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "correlate",
        "description": (
            "Pearson r between metric_a (a lab) and metric_b (a lab or a "
            "nutrition column like kcal/protein_g/carb_g/fat_g/fiber_g) "
            "over the last window_days."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_a":    {"type": "string"},
                "metric_b":    {"type": "string"},
                "window_days": {"type": "integer", "default": 365},
            },
            "required": ["metric_a", "metric_b"],
        },
    },
]

TOOL_FUNCS: dict[str, Callable[..., dict]] = {
    "list_metrics":           list_metrics,
    "get_lab_series":         get_lab_series,
    "get_lab_window_summary": get_lab_window_summary,
    "get_nutrition_window":   get_nutrition_window,
    "get_body_composition":   get_body_composition,
    "get_lift_prs":           get_lift_prs,
    "get_sleep_window":       get_sleep_window,
    "get_traits":             get_traits,
    "get_events":             get_events,
    "correlate":              correlate,
}


def dispatch(tool: str, args: dict) -> dict:
    """Run a tool by name. Args dict from the model."""
    fn = TOOL_FUNCS.get(tool)
    if fn is None:
        return {"error": f"unknown tool: {tool}"}
    try:
        return fn(**args)
    except TypeError as e:
        return {"error": f"bad args for {tool}: {e}"}
