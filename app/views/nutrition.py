"""
Nutrition view — macros over time, with gene-adjusted target overlay
(joining `nutrient_targets` from Pattern C).
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app import db


def render() -> None:
    st.title("Nutrition")
    st.caption("Daily macros + gene-adjusted nutrient targets.")

    days = int(st.query_params.get("days", 90))
    days = st.number_input("Window (days)", min_value=7, max_value=730, value=days, step=7)
    df = db.read_sql_safe(
        "SELECT date, kcal, protein_g, carb_g, fat_g, fiber_g, sugar_g, sodium_mg, source "
        f"FROM nutrition_daily WHERE date >= date('now','-{int(days)} days') ORDER BY date"
    )
    if df.empty:
        st.info("No nutrition rows. Run `python -m ingest.nutrition`.")
        return

    df["date"] = pd.to_datetime(df["date"])

    # Macros stacked area
    melted = df.melt(
        id_vars=["date", "source"],
        value_vars=["protein_g", "carb_g", "fat_g"],
        var_name="macro",
        value_name="grams",
    )
    chart = alt.Chart(melted).mark_area(opacity=0.7).encode(
        x="date:T", y="grams:Q", color="macro:N", tooltip=["date", "macro", "grams"],
    ).properties(title="Macros (g)", height=320)
    st.altair_chart(chart, use_container_width=True)

    # Calories line
    kcal_chart = alt.Chart(df).mark_line(point=True).encode(
        x="date:T", y="kcal:Q", tooltip=["date", "kcal"],
    ).properties(title="Calories", height=200)
    st.altair_chart(kcal_chart, use_container_width=True)

    # Gene-adjusted targets (Pattern C output)
    tgt = db.read_sql_safe("SELECT nutrient, target_value, unit, computed_at FROM nutrient_targets")
    st.subheader("Gene-adjusted targets")
    if tgt.empty:
        st.caption(
            "No `nutrient_targets` rows. Run `python -m app.synthesis.calculators` "
            "after the genome ingest populates `snps`."
        )
    else:
        st.dataframe(tgt, use_container_width=True, hide_index=True)

    st.subheader("Raw rows")
    st.dataframe(df, use_container_width=True, hide_index=True)
