"""
Pattern B (part 1) — changepoint detection on lab series.

A simple, deterministic changepoint: walk a smoothed lab series and flag
points where the rolling mean of the next K observations differs from
the rolling mean of the prior K observations by more than `threshold`
standard deviations.

Output: a DataFrame of (metric, date, prior_mean, next_mean, delta, z).
Callers (Labs view, Home page) render these as markers on the line chart.

This is deliberately not the most sophisticated method. We want:
  - reproducible (same input -> same flags),
  - cheap (no scipy required),
  - explainable (Will sees "the mean before X was Y; after, it was Z").
"""

from __future__ import annotations

import pandas as pd

from app import db


def detect_inflections(metric: str, window: int = 5, threshold_z: float = 1.5) -> pd.DataFrame:
    """Return a DataFrame of inflection rows for `metric`.

    `window` is the half-window in observations (not days). With Will's
    bloodwork cadence (quarterly), window=5 corresponds to ~5 visits.
    """
    df = db.read_sql_safe(
        "SELECT date, value FROM labs WHERE metric = ? ORDER BY date",
        (metric,),
    )
    if df.empty or len(df) < 2 * window + 1:
        return pd.DataFrame(columns=["metric", "date", "prior_mean", "next_mean", "delta", "z"])

    df = df.copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"]).reset_index(drop=True)
    if len(df) < 2 * window + 1:
        return pd.DataFrame(columns=["metric", "date", "prior_mean", "next_mean", "delta", "z"])

    out_rows: list[dict] = []
    overall_std = df["value"].std()
    if overall_std == 0 or pd.isna(overall_std):
        return pd.DataFrame(columns=["metric", "date", "prior_mean", "next_mean", "delta", "z"])

    for i in range(window, len(df) - window):
        prior = df["value"].iloc[i - window:i]
        nxt = df["value"].iloc[i + 1:i + 1 + window]
        pm = prior.mean()
        nm = nxt.mean()
        delta = nm - pm
        z = abs(delta) / overall_std
        if z >= threshold_z:
            out_rows.append(
                {
                    "metric": metric,
                    "date":   df["date"].iloc[i],
                    "prior_mean": float(pm),
                    "next_mean":  float(nm),
                    "delta":      float(delta),
                    "z":          float(z),
                }
            )

    return pd.DataFrame(out_rows)


def detect_for_all_metrics(threshold_z: float = 1.5) -> pd.DataFrame:
    """Run detection across every metric in `labs` and concat."""
    metrics = db.read_sql_safe("SELECT DISTINCT metric FROM labs")
    if metrics.empty:
        return pd.DataFrame()
    frames: list[pd.DataFrame] = []
    for m in metrics["metric"]:
        frames.append(detect_inflections(m, threshold_z=threshold_z))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)
