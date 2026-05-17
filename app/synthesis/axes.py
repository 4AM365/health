"""
Pattern A — six axis composites for the Home page.

Each axis is a 0-100 composite score over the last 30 days from one or two
underlying tables. Designed so a missing domain returns a `None` value
without crashing the home page.

Axes:
  - cardiometabolic   (labs: LDL, HDL, triglycerides, HbA1c, fasting glucose)
  - inflammation      (labs: hsCRP, ferritin, neutrophil/lymphocyte ratio)
  - body              (body_comp: BF%, lean mass trend, VAT)
  - strength          (lifts: e1RM trend across top compound lifts)
  - recovery          (sleep: total_hr, deep_hr, hr_avg)
  - nutrition         (nutrition_daily: protein, fiber, kcal vs personal baseline)

A composite is "good" when:
  - lab metrics are inside their ref-range,
  - body comp / strength / recovery / nutrition moves in the desired
    direction vs the prior 30-day window.

This is a coarse signal — the underlying chart is the source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from app import db


@dataclass(frozen=True)
class AxisScore:
    name: str
    value: Optional[float]   # 0-100 or None
    direction: str           # "up", "down", "flat", "none"
    note: str
    n_inputs: int            # how many underlying signals contributed


def _safe_pct_in_range(df: pd.DataFrame) -> Optional[float]:
    """For a labs subset with value/ref_low/ref_high, % rows in range."""
    if df.empty:
        return None
    valid = df.dropna(subset=["value"]).copy()
    if valid.empty:
        return None

    def within(row: pd.Series) -> bool:
        v = row["value"]
        lo = row.get("ref_low")
        hi = row.get("ref_high")
        if lo is not None and pd.notna(lo) and v < lo:
            return False
        if hi is not None and pd.notna(hi) and v > hi:
            return False
        return True

    return float(valid.apply(within, axis=1).mean() * 100.0)


def _axis_from_labs(name: str, metrics: list[str]) -> AxisScore:
    placeholder = ",".join("?" * len(metrics))
    q = f"""
    SELECT metric, value, ref_low, ref_high, date
    FROM labs
    WHERE metric IN ({placeholder}) AND date >= date('now','-365 days')
    """
    df = db.read_sql_safe(q, tuple(metrics))
    if df.empty:
        return AxisScore(name=name, value=None, direction="none", note="no labs", n_inputs=0)
    # latest per metric
    latest = df.sort_values("date").groupby("metric", as_index=False).tail(1)
    pct = _safe_pct_in_range(latest)
    return AxisScore(
        name=name,
        value=pct,
        direction="flat",
        note=f"{len(latest)} of {len(metrics)} metrics observed",
        n_inputs=int(len(latest)),
    )


def _axis_body() -> AxisScore:
    df = db.read_sql_safe(
        "SELECT date, bf_pct, lbm_kg, vat_g FROM body_comp ORDER BY date"
    )
    if df.empty:
        return AxisScore(name="body", value=None, direction="none", note="no DEXA", n_inputs=0)
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else None
    # Rough score: lower BF% + higher LBM = better. Map to 0-100 using sane bounds.
    bf = last.get("bf_pct")
    score = None
    if bf is not None and pd.notna(bf):
        score = max(0.0, min(100.0, 100.0 - (bf - 8.0) * 4.0))  # 8% -> 100; 33% -> 0
    direction = "flat"
    if prev is not None and bf is not None and pd.notna(prev.get("bf_pct")):
        if bf < prev["bf_pct"]:
            direction = "down"  # lower BF% — favorable
        elif bf > prev["bf_pct"]:
            direction = "up"
    return AxisScore(
        name="body",
        value=score,
        direction=direction,
        note=f"latest BF%={bf:.1f}" if score is not None else "missing BF%",
        n_inputs=int(len(df)),
    )


def _axis_strength() -> AxisScore:
    df = db.read_sql_safe(
        """
        SELECT date, lift, MAX(e1rm) AS e1rm
        FROM lifts
        WHERE date >= date('now','-365 days')
        GROUP BY date, lift
        ORDER BY date
        """
    )
    if df.empty:
        return AxisScore(name="strength", value=None, direction="none", note="no lifts", n_inputs=0)
    # Compare last 30d e1rm vs prior 30-90d
    recent = df[df["date"] >= (pd.Timestamp.now().normalize() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")]
    prior = df[
        (df["date"] >= (pd.Timestamp.now().normalize() - pd.Timedelta(days=90)).strftime("%Y-%m-%d"))
        & (df["date"] < (pd.Timestamp.now().normalize() - pd.Timedelta(days=30)).strftime("%Y-%m-%d"))
    ]
    if recent.empty:
        return AxisScore(name="strength", value=None, direction="none", note="no recent lifts", n_inputs=int(len(df)))
    r_max = recent.groupby("lift")["e1rm"].max()
    p_max = prior.groupby("lift")["e1rm"].max() if not prior.empty else None
    if p_max is None or p_max.empty:
        score = 50.0
        direction = "flat"
        note = f"{len(r_max)} lifts (no prior window)"
    else:
        common = r_max.index.intersection(p_max.index)
        if len(common) == 0:
            score = 50.0
            direction = "flat"
            note = f"{len(r_max)} lifts (no overlap)"
        else:
            pct_change = ((r_max[common] - p_max[common]) / p_max[common]).mean() * 100.0
            score = max(0.0, min(100.0, 50.0 + pct_change * 5.0))  # 10% gain = 100
            direction = "up" if pct_change > 0.5 else "down" if pct_change < -0.5 else "flat"
            note = f"avg Δe1rm {pct_change:+.1f}% across {len(common)} lifts"
    return AxisScore(name="strength", value=score, direction=direction, note=note, n_inputs=int(len(r_max)))


def _axis_recovery() -> AxisScore:
    df = db.read_sql_safe(
        "SELECT date, total_hr, deep_hr, rem_hr, hr_avg FROM sleep WHERE date >= date('now','-90 days') ORDER BY date"
    )
    if df.empty:
        return AxisScore(name="recovery", value=None, direction="none", note="no sleep data", n_inputs=0)
    last30 = df.tail(30)
    prior60 = df.iloc[:-30] if len(df) > 30 else df
    avg_total = last30["total_hr"].mean()
    if pd.isna(avg_total):
        return AxisScore(name="recovery", value=None, direction="none", note="no total_hr", n_inputs=int(len(df)))
    # Map 8h -> 100, 5h -> 0
    score = max(0.0, min(100.0, (avg_total - 5.0) / 3.0 * 100.0))
    direction = "flat"
    if not prior60.empty:
        prior_avg = prior60["total_hr"].mean()
        if pd.notna(prior_avg):
            if avg_total > prior_avg + 0.1:
                direction = "up"
            elif avg_total < prior_avg - 0.1:
                direction = "down"
    return AxisScore(
        name="recovery",
        value=score,
        direction=direction,
        note=f"30d avg {avg_total:.1f}h/night",
        n_inputs=int(len(last30)),
    )


def _axis_nutrition() -> AxisScore:
    df = db.read_sql_safe(
        "SELECT date, kcal, protein_g, fiber_g FROM nutrition_daily WHERE date >= date('now','-30 days')"
    )
    if df.empty:
        return AxisScore(name="nutrition", value=None, direction="none", note="no nutrition data", n_inputs=0)
    # Three sub-scores
    p = df["protein_g"].mean()
    f = df["fiber_g"].mean()
    # Heuristic: 1.6 g/kg protein @ 80kg = 128g target; fiber 30g target
    sub_p = max(0.0, min(100.0, p / 128.0 * 100.0)) if pd.notna(p) else None
    sub_f = max(0.0, min(100.0, f / 30.0 * 100.0)) if pd.notna(f) else None
    vals = [v for v in (sub_p, sub_f) if v is not None]
    score = float(sum(vals) / len(vals)) if vals else None
    note = (
        f"protein avg {p:.0f}g, fiber avg {f:.0f}g over {len(df)}d"
        if pd.notna(p) and pd.notna(f)
        else f"{len(df)}d of data"
    )
    return AxisScore(name="nutrition", value=score, direction="flat", note=note, n_inputs=int(len(df)))


def compute_all() -> list[AxisScore]:
    """The six axes. Order is the Home tile order."""
    return [
        _axis_from_labs("cardiometabolic", ["LDL", "HDL", "Triglycerides", "HbA1c", "Glucose"]),
        _axis_from_labs("inflammation",    ["hsCRP", "Ferritin", "WBC"]),
        _axis_body(),
        _axis_strength(),
        _axis_recovery(),
        _axis_nutrition(),
    ]
