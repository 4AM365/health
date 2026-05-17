"""
Ask view — full-window chat, no view scoping.

Per UI_STRUCTURE.md §2: "open in a fresh thread, no view context attached."
"""

from __future__ import annotations

import streamlit as st

from app.components import chat_panel


def render() -> None:
    st.title("Ask")
    st.caption(
        "Free-text chat over your data. Tools are read-only; raw rsids and "
        "pedigree are filtered (see `docs/LLM_INTERFACE.md` §4)."
    )
    chat_panel(page="ask", context_params=None, height=600)
