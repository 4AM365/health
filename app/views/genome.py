"""
Genome view — derived traits grouped by category.

CRITICAL: never queries `snps`, never renders raw rsids in the UI.
Only the `traits` table is consulted.
"""

from __future__ import annotations

import streamlit as st

from app import db


def render() -> None:
    st.title("Genome (derived traits)")
    st.caption(
        "Derived traits only. Raw rsids/genotypes live in `snps` (gitignored "
        "from LLM context per `docs/LLM_INTERFACE.md` §3) and are never "
        "displayed here. Family conditions are surfaced separately on Family."
    )

    df = db.read_sql_safe(
        "SELECT trait, category, value, source, confidence, notes FROM traits "
        "ORDER BY category, trait"
    )
    if df.empty:
        st.info("No traits ingested yet. Run `python -m ingest.genome`.")
        return

    category_filter = st.query_params.get("category")
    cats = ["(all)"] + sorted(df["category"].dropna().unique().tolist())
    default_idx = cats.index(category_filter) if category_filter in cats else 0
    pick = st.selectbox("Category", cats, index=default_idx)
    if pick != "(all)":
        df = df[df["category"] == pick]

    st.dataframe(df, use_container_width=True, hide_index=True)

    # Family conditions (relationship-coded only)
    st.subheader("Family conditions (relationship-coded only)")
    from app.synthesis import priors
    fh = priors.family_history_flags()
    if fh.empty:
        st.caption("No `pedigree_conditions` rows yet.")
    else:
        st.dataframe(fh, use_container_width=True, hide_index=True)
