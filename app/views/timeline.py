"""Timeline view — cross-domain events filter."""

from __future__ import annotations

import streamlit as st

from app import db


def render() -> None:
    st.title("Timeline")
    st.caption("Cross-domain events. Filter by domain and date range.")

    df = db.read_sql_safe(
        "SELECT date, domain, event_type, summary FROM events ORDER BY date DESC"
    )
    if df.empty:
        st.info(
            "No events yet. Ingest agents write to `events` (e.g. lab "
            "inflections, lift PRs, DEXA scans)."
        )
        return

    domains = ["(all)"] + sorted(df["domain"].dropna().unique().tolist())
    pick = st.selectbox("Domain", domains)
    if pick != "(all)":
        df = df[df["domain"] == pick]

    since = st.query_params.get("since")
    until = st.query_params.get("until")
    if since:
        df = df[df["date"] >= since]
    if until:
        df = df[df["date"] <= until]

    st.dataframe(df, use_container_width=True, hide_index=True)
