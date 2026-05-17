"""
Labs view — marker picker, personal-baseline band + ref-range, inflection
markers (Pattern B).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import db
from app.components import series_chart
from app.synthesis import inflections


def _metrics_list() -> list[str]:
    df = db.read_sql_safe("SELECT DISTINCT metric FROM labs ORDER BY metric")
    return df["metric"].tolist() if not df.empty else []


def render() -> None:
    st.title("Labs")
    st.caption("Pick a metric to see trend, reference range, and inflection points.")

    metrics = _metrics_list()
    if not metrics:
        st.info("No labs ingested yet. Run `python -m ingest.bloodwork`.")
        return

    # Read query params for deep-linking
    default_metric = st.query_params.get("metric")
    if default_metric and default_metric not in metrics:
        st.warning(f"Filter `metric={default_metric}` not found; showing first available.")
        default_metric = None
    idx = metrics.index(default_metric) if default_metric in metrics else 0
    metric = st.selectbox("Metric", metrics, index=idx)

    since = st.query_params.get("since")
    until = st.query_params.get("until")

    # Pull series
    q = "SELECT date, value, ref_low, ref_high FROM labs WHERE metric = ?"
    params: list = [metric]
    if since:
        q += " AND date >= ?"
        params.append(since)
    if until:
        q += " AND date <= ?"
        params.append(until)
    q += " ORDER BY date"
    df = db.read_sql_safe(q, tuple(params))

    if df.empty:
        st.info(f"No rows for `{metric}`.")
        return

    # Reference range (mode of ref_low / ref_high; ranges sometimes drift between labs)
    ref_low = None
    ref_high = None
    if "ref_low" in df.columns:
        lo = df["ref_low"].dropna()
        if not lo.empty:
            ref_low = float(lo.mode().iloc[0])
    if "ref_high" in df.columns:
        hi = df["ref_high"].dropna()
        if not hi.empty:
            ref_high = float(hi.mode().iloc[0])

    # Inflections (Pattern B)
    infl = inflections.detect_inflections(metric)

    series_chart(df, ref_low=ref_low, ref_high=ref_high, inflections=infl, title=metric)

    # Personal-baseline band note
    p10, p50, p90 = df["value"].quantile([0.1, 0.5, 0.9])
    st.caption(
        f"Personal baseline (10/50/90 pctile): {p10:.2f} / {p50:.2f} / {p90:.2f}  "
        + (f"·  ref-range: [{ref_low}, {ref_high}]" if ref_low is not None else "")
    )

    if not infl.empty:
        st.subheader("Inflection points")
        st.dataframe(infl, use_container_width=True, hide_index=True)

    st.subheader("Raw rows")
    st.dataframe(df, use_container_width=True, hide_index=True)
