"""
Pattern B (part 2) — counterfactual window diff.

Given an anchor date (typically from an inflection point), compare the
30-day window BEFORE and AFTER across every domain. Output is a single
DataFrame the UI can render as a "what changed?" table.

This is the deterministic core of "why did my HDL drop in March?" — the
LLM only narrates over this output (CLAUDE.md §6).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from app import db


@dataclass(frozen=True)
class DomainDiff:
    domain: str
    metric: str
    before: Optional[float]
    after: Optional[float]
    delta: Optional[float]
    delta_pct: Optional[float]
    n_before: int
    n_after: int


def _diff_one(before: pd.Series, after: pd.Series) -> tuple[Optional[float], Optional[float], Optional[float]]:
    b = before.dropna().mean() if not before.empty else None
    a = after.dropna().mean() if not after.empty else None
    if b is None or a is None or pd.isna(b) or pd.isna(a):
        return (
            float(b) if b is not None and not pd.isna(b) else None,
            float(a) if a is not None and not pd.isna(a) else None,
            None,
        )
    delta = a - b
    return float(b), float(a), float(delta)


def _delta_pct(before: Optional[float], after: Optional[float]) -> Optional[float]:
    if before is None or after is None or before == 0:
        return None
    return (after - before) / before * 100.0


def window_diff(anchor: str, window_days: int = 30) -> pd.DataFrame:
    """Compare the window BEFORE `anchor` to the window AFTER.

    `anchor` is an ISO date. Returns one row per (domain, metric).
    """
    try:
        anchor_dt = dt.date.fromisoformat(anchor)
    except ValueError:
        return pd.DataFrame()

    start_before = (anchor_dt - dt.timedelta(days=window_days)).isoformat()
    end_after = (anchor_dt + dt.timedelta(days=window_days)).isoformat()
    rows: list[DomainDiff] = []

    # 1) nutrition
    n = db.read_sql_safe(
        "SELECT date, kcal, protein_g, carb_g, fat_g, fiber_g, sugar_g, sodium_mg "
        "FROM nutrition_daily WHERE date >= ? AND date <= ?",
        (start_before, end_after),
    )
    if not n.empty:
        for col in ("kcal", "protein_g", "carb_g", "fat_g", "fiber_g", "sugar_g", "sodium_mg"):
            before = n[n["date"] < anchor][col]
            after = n[n["date"] >= anchor][col]
            b, a, d = _diff_one(before, after)
            rows.append(DomainDiff(
                "nutrition", col, b, a, d, _delta_pct(b, a),
                int(before.notna().sum()), int(after.notna().sum()),
            ))

    # 2) sleep
    s = db.read_sql_safe(
        "SELECT date, total_hr, deep_hr, rem_hr, hr_avg "
        "FROM sleep WHERE date >= ? AND date <= ?",
        (start_before, end_after),
    )
    if not s.empty:
        for col in ("total_hr", "deep_hr", "rem_hr", "hr_avg"):
            before = s[s["date"] < anchor][col]
            after = s[s["date"] >= anchor][col]
            b, a, d = _diff_one(before, after)
            rows.append(DomainDiff(
                "sleep", col, b, a, d, _delta_pct(b, a),
                int(before.notna().sum()), int(after.notna().sum()),
            ))

    # 3) lifts (mean e1rm across all lifts)
    l_ = db.read_sql_safe(
        "SELECT date, e1rm FROM lifts WHERE date >= ? AND date <= ?",
        (start_before, end_after),
    )
    if not l_.empty:
        before = l_[l_["date"] < anchor]["e1rm"]
        after = l_[l_["date"] >= anchor]["e1rm"]
        b, a, d = _diff_one(before, after)
        rows.append(DomainDiff(
            "lifts", "e1rm_avg", b, a, d, _delta_pct(b, a),
            int(before.notna().sum()), int(after.notna().sum()),
        ))

    # 4) labs (per metric)
    lab = db.read_sql_safe(
        "SELECT date, metric, value FROM labs WHERE date >= ? AND date <= ?",
        (start_before, end_after),
    )
    if not lab.empty:
        for metric_name, grp in lab.groupby("metric"):
            before = grp[grp["date"] < anchor]["value"]
            after = grp[grp["date"] >= anchor]["value"]
            b, a, d = _diff_one(before, after)
            rows.append(DomainDiff(
                "labs", str(metric_name), b, a, d, _delta_pct(b, a),
                int(before.notna().sum()), int(after.notna().sum()),
            ))

    return pd.DataFrame(
        [{
            "domain": r.domain, "metric": r.metric,
            "before": r.before, "after": r.after,
            "delta": r.delta, "delta_pct": r.delta_pct,
            "n_before": r.n_before, "n_after": r.n_after,
        } for r in rows]
    )
