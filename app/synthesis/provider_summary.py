"""
Pattern F — provider conversation prep.

A one-pager rollup the user can take to a doctor visit. Pure data; no LLM.
Pulls:
  - Recent labs trending out of range,
  - Family-history flags,
  - Overdue screenings,
  - Risk-score deltas (if `risk_scores` populated).

Output: dict with sections the dashboard renders as a card.
"""

from __future__ import annotations

import datetime as dt
import pandas as pd

from app import db
from . import priors, screening


def _recent_out_of_range_labs(window_days: int = 365) -> pd.DataFrame:
    cutoff = (dt.date.today() - dt.timedelta(days=window_days)).isoformat()
    df = db.read_sql_safe(
        """
        SELECT date, metric, value, ref_low, ref_high
        FROM labs WHERE date >= ?
        """,
        (cutoff,),
    )
    if df.empty:
        return df

    def out_of_range(row: pd.Series) -> bool:
        v = row.get("value")
        if v is None or pd.isna(v):
            return False
        lo = row.get("ref_low")
        hi = row.get("ref_high")
        if lo is not None and pd.notna(lo) and v < lo:
            return True
        if hi is not None and pd.notna(hi) and v > hi:
            return True
        return False

    df["oor"] = df.apply(out_of_range, axis=1)
    # Keep just the latest OOR row per metric
    oor = df[df["oor"]].sort_values("date").groupby("metric", as_index=False).tail(1)
    return oor[["date", "metric", "value", "ref_low", "ref_high"]]


def _risk_deltas() -> pd.DataFrame:
    df = db.read_sql_safe(
        "SELECT date, score_id, value, percentile FROM risk_scores ORDER BY date"
    )
    if df.empty:
        return df
    latest = df.sort_values("date").groupby("score_id", as_index=False).tail(1)
    return latest


def build() -> dict:
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "out_of_range_labs":   _recent_out_of_range_labs(),
        "family_history":       priors.family_history_flags(),
        "screening_overlay":    screening.overlay(),
        "risk_scores":          _risk_deltas(),
    }
