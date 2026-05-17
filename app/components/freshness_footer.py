"""Sidebar footer showing per-source last-run age (W9 mitigation)."""

from __future__ import annotations

import datetime as dt
import pandas as pd
import streamlit as st


def freshness_footer(meta_df: pd.DataFrame, threshold_days: int = 7) -> None:
    """Render the freshness footer. Yellow when stale per threshold."""
    st.markdown("---")
    st.caption("**Data freshness**")
    if meta_df is None or meta_df.empty:
        st.caption("(no ingest_meta rows; run `python -m ingest.<domain>`)")
        return

    today = dt.date.today()
    for _, row in meta_df.iterrows():
        last = row.get("last_run")
        try:
            last_dt = dt.datetime.fromisoformat(str(last).replace("Z", "")).date()
            days = (today - last_dt).days
            mark = "✓" if days <= threshold_days else "⚠"
            st.caption(f"{mark} {row['source']}: {last_dt} ({days}d)")
        except (TypeError, ValueError):
            st.caption(f"? {row['source']}: unknown")
