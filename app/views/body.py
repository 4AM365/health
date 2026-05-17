"""
Body view — DEXA + lifts (e1rm) + sleep small-multiples.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app import db


def render() -> None:
    st.title("Body")
    st.caption("DEXA snapshots, lift e1RM trends, sleep stages.")

    view = st.query_params.get("view") or "all"
    view = st.radio("Show", ["all", "DEXA", "lifts", "sleep"], horizontal=True, index=["all","DEXA","lifts","sleep"].index(view) if view in ["all","DEXA","lifts","sleep"] else 0)

    if view in ("all", "DEXA"):
        st.subheader("DEXA")
        bc = db.read_sql_safe("SELECT date, bf_pct, lbm_kg, fat_mass_kg, vat_g, bmd FROM body_comp ORDER BY date")
        if bc.empty:
            st.caption("No DEXA scans yet.")
        else:
            bc["date"] = pd.to_datetime(bc["date"])
            for col in ("bf_pct", "lbm_kg", "vat_g"):
                if col in bc.columns and bc[col].notna().any():
                    c = alt.Chart(bc.dropna(subset=[col])).mark_line(point=True).encode(
                        x="date:T", y=alt.Y(f"{col}:Q", title=col),
                    ).properties(height=160, title=col)
                    st.altair_chart(c, use_container_width=True)

    if view in ("all", "lifts"):
        st.subheader("Lifts")
        lifts = db.read_sql_safe(
            "SELECT date, lift, MAX(e1rm) AS e1rm FROM lifts GROUP BY date, lift ORDER BY date"
        )
        if lifts.empty:
            st.caption("No lifts ingested.")
        else:
            lifts["date"] = pd.to_datetime(lifts["date"])
            chart = alt.Chart(lifts).mark_line(point=True).encode(
                x="date:T", y="e1rm:Q", color="lift:N", tooltip=["date", "lift", "e1rm"],
            ).properties(height=320)
            st.altair_chart(chart, use_container_width=True)

    if view in ("all", "sleep"):
        st.subheader("Sleep")
        slp = db.read_sql_safe(
            "SELECT date, total_hr, rem_hr, deep_hr, light_hr, awake_hr FROM sleep "
            "WHERE date >= date('now','-180 days') ORDER BY date"
        )
        if slp.empty:
            st.caption("No sleep data.")
        else:
            slp["date"] = pd.to_datetime(slp["date"])
            stages = slp.melt(id_vars=["date"], value_vars=["rem_hr", "deep_hr", "light_hr"],
                              var_name="stage", value_name="hours")
            c = alt.Chart(stages).mark_area(opacity=0.7).encode(
                x="date:T", y="hours:Q", color="stage:N",
            ).properties(height=240, title="Stages")
            st.altair_chart(c, use_container_width=True)

            total = alt.Chart(slp).mark_line(point=True).encode(
                x="date:T", y="total_hr:Q",
            ).properties(height=160, title="Total hours")
            st.altair_chart(total, use_container_width=True)
