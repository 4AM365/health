"""Sources view — ingest freshness, row counts."""

from __future__ import annotations

import streamlit as st

from app import db


def render() -> None:
    st.title("Sources")
    st.caption("What's been ingested, when, and how many rows.")

    meta = db.ingest_meta()
    if meta.empty:
        st.info(
            "No ingest_meta rows. Each domain agent's parser writes one row "
            "to `ingest_meta` when it finishes. Run `python -m ingest.bloodwork` etc."
        )
    else:
        st.dataframe(meta, use_container_width=True, hide_index=True)

    # Row counts across all domain tables
    st.subheader("Row counts")
    tables = [
        "labs", "nutrition_daily", "snps", "traits", "pedigree",
        "pedigree_conditions", "body_comp", "lifts", "sleep", "events",
        "nutrient_targets", "risk_scores", "ingest_meta",
    ]
    counts: list[dict] = []
    for t in tables:
        cnt = db.read_sql_safe(f"SELECT COUNT(*) AS n FROM {t}")
        counts.append({"table": t, "n": int(cnt.iloc[0]["n"]) if not cnt.empty else 0})
    import pandas as pd
    st.dataframe(pd.DataFrame(counts), use_container_width=True, hide_index=True)
