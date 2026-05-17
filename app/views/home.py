"""
Home view — daily brief (Pattern G) + six axis composites (Pattern A) +
freshness banner (W9 mitigation).
"""

from __future__ import annotations

import streamlit as st

from app import db
from app.components import kpi_card
from app.llm import brief as brief_mod, agent
from app.synthesis import axes


def render() -> None:
    st.title("Home")
    st.caption("Daily brief, axis composites, freshness. Read-only.")

    # 1. Daily brief (Pattern G)
    if agent.llm_enabled():
        with st.spinner("Loading today's brief..."):
            b = brief_mod.daily_brief()
        if b.get("any_stale"):
            st.warning(
                f"Some data is stale. Run ingests for current view.\n\n```\n{b['freshness_summary']}\n```"
            )
        st.subheader("Daily brief")
        if b.get("error"):
            st.error(b["error"])
        elif b.get("text"):
            st.markdown(b["text"])
            if b.get("from_cache"):
                st.caption(f"_cached for {b['date']}_")
        else:
            st.info("No brief generated yet. Run with data populated.")
    else:
        # W5: LLM-off graceful fallback
        st.info(
            "Set `ANTHROPIC_API_KEY` to enable narrative briefs. "
            "All charts below work without the LLM."
        )
        fresh, any_stale = brief_mod.freshness_report()
        if any_stale:
            st.warning(f"Some data is stale:\n\n```\n{fresh}\n```")

    # 2. Six axis composites
    st.subheader("Composites (last 30 days)")
    scores = axes.compute_all()
    cols = st.columns(3)
    for i, sc in enumerate(scores):
        with cols[i % 3]:
            kpi_card(sc.name, sc.value, sc.direction, sc.note)

    # 3. Recent events
    st.subheader("Recent events")
    ev = db.read_sql_safe(
        "SELECT date, domain, event_type, summary FROM events ORDER BY date DESC LIMIT 10"
    )
    if ev.empty:
        st.caption("No events yet. Ingests will write to `events`.")
    else:
        st.dataframe(ev, use_container_width=True, hide_index=True)
