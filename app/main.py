"""
Dashboard entrypoint.

Three-zone layout per docs/UI_STRUCTURE.md §1:
  - left rail (st.sidebar): nav + freshness footer
  - main pane (`st.columns`): active view
  - right rail: collapsible chat (st.expander on small layouts, column on wide)

The chat is available from every page; the Ask page is the full-window
fallback. Pages route on `st.query_params["page"]` so citation chips can
deep-link.

W5 mitigation: dashboard launches without ANTHROPIC_API_KEY; the chat
panel renders a "set ANTHROPIC_API_KEY" hint instead of failing.

W9 mitigation: freshness footer is in the sidebar; the Home page also
shows a banner above the brief when any source is >7 days stale.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow `python -m streamlit run app/main.py` from repo root
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app import db  # noqa: E402
from app.components import freshness_footer, chat_panel  # noqa: E402
from app.llm import agent  # noqa: E402
from app.views import home, labs, nutrition, body, genome, timeline, ask, sources  # noqa: E402

st.set_page_config(page_title="Health Dashboard", layout="wide")

PAGES = {
    "home":      ("Home",      home.render),
    "labs":      ("Labs",      labs.render),
    "nutrition": ("Nutrition", nutrition.render),
    "body":      ("Body",      body.render),
    "genome":    ("Genome",    genome.render),
    "timeline":  ("Timeline",  timeline.render),
    "ask":       ("Ask",       ask.render),
    "sources":   ("Sources",   sources.render),
}


def _current_page() -> str:
    qp = st.query_params.get("page")
    if qp in PAGES:
        return qp
    return "home"


def _set_page(slug: str) -> None:
    st.query_params.clear()
    st.query_params["page"] = slug


def _sidebar() -> None:
    st.sidebar.title("Health")
    current = _current_page()
    for slug, (label, _) in PAGES.items():
        if st.sidebar.button(label, key=f"nav_{slug}", use_container_width=True,
                              type="primary" if slug == current else "secondary"):
            _set_page(slug)
            st.rerun()

    st.sidebar.markdown("---")
    # LLM status indicator
    if agent.llm_enabled():
        st.sidebar.caption("LLM: on")
    else:
        st.sidebar.caption("LLM: off (set `ANTHROPIC_API_KEY`)")

    # Freshness footer (W9)
    freshness_footer(db.ingest_meta())

    if not db.db_exists():
        st.sidebar.warning(
            "No `analysis/health.db` yet. Run `sqlite3 analysis/health.db < schema.sql` "
            "and then any `python -m ingest.<domain>` to populate."
        )


def _main() -> None:
    _sidebar()
    page = _current_page()

    # Three-zone layout. Right column is the chat panel; users can collapse
    # it by clicking "Hide chat".
    show_chat = st.session_state.get("show_chat", True)
    if show_chat:
        main_col, chat_col = st.columns([3, 1], gap="medium")
    else:
        main_col = st.container()
        chat_col = None

    with main_col:
        _, render_fn = PAGES[page]
        render_fn()
        # Toggle chat
        cols = st.columns([8, 1])
        with cols[1]:
            if st.button("Hide chat" if show_chat else "Show chat", key="toggle_chat"):
                st.session_state["show_chat"] = not show_chat
                st.rerun()

    if chat_col is not None and page != "ask":
        # Right rail chat — inherits the page's query params as context
        ctx = {k: v for k, v in st.query_params.items() if k != "page"}
        with chat_col:
            chat_panel(page=page, context_params=ctx, height=520)


if __name__ == "__main__" or os.environ.get("STREAMLIT_SERVER_ENABLE_STATIC_SERVING") is not None:
    _main()
else:
    # Streamlit imports this module as a script; running _main() at import-
    # time ensures the page renders.
    _main()
