"""KPI tile used on Home for axis composites."""

from __future__ import annotations

import streamlit as st


def kpi_card(label: str, value: float | None, direction: str = "flat", note: str = "") -> None:
    """One axis tile."""
    arrow = {"up": "↑", "down": "↓", "flat": "→", "none": "·"}[direction or "none"]
    if value is None:
        st.metric(label=f"{label} {arrow}", value="—", delta=note or "no data")
    else:
        st.metric(label=f"{label} {arrow}", value=f"{value:.0f}", delta=note or "")
