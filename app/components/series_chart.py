"""series_chart — a line/scatter with optional ref-range bands and inflection markers."""

from __future__ import annotations

from typing import Optional

import altair as alt
import pandas as pd
import streamlit as st


def series_chart(
    df: pd.DataFrame,
    value_col: str = "value",
    date_col: str = "date",
    ref_low: Optional[float] = None,
    ref_high: Optional[float] = None,
    inflections: Optional[pd.DataFrame] = None,
    title: str = "",
) -> None:
    """Render a time series with optional ref-range and inflection markers.

    `df` requires `date_col` and `value_col`.
    `inflections` requires `date` column for the marker positions.
    """
    if df is None or df.empty:
        st.info("No data for this view.")
        return

    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    chart = alt.Chart(df).mark_line(point=True).encode(
        x=alt.X(f"{date_col}:T", title="Date"),
        y=alt.Y(f"{value_col}:Q", title=value_col),
        tooltip=[date_col, value_col],
    )

    layers = [chart]

    # Ref-range band
    if ref_low is not None and ref_high is not None:
        band_df = pd.DataFrame({"y1": [ref_low], "y2": [ref_high]})
        band = alt.Chart(band_df).mark_rect(opacity=0.08, color="green").encode(
            y="y1:Q", y2="y2:Q",
        )
        layers.insert(0, band)

    # Inflection markers
    if inflections is not None and not inflections.empty:
        inflect_df = inflections.copy()
        inflect_df[date_col] = pd.to_datetime(inflect_df[date_col])
        # Need a value to anchor each marker to. Use the next_mean column if present.
        if "next_mean" in inflect_df.columns:
            inflect_df["value"] = inflect_df["next_mean"]
        else:
            inflect_df["value"] = df[value_col].mean()
        markers = alt.Chart(inflect_df).mark_rule(color="red", strokeDash=[4, 4]).encode(
            x=f"{date_col}:T",
            tooltip=[date_col] + [c for c in inflect_df.columns if c not in (date_col,)],
        )
        layers.append(markers)

    layered = alt.layer(*layers).properties(title=title, height=320)
    st.altair_chart(layered, use_container_width=True)
