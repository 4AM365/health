"""chat_panel — right-rail chat per UI_STRUCTURE.md §3.

Three states: idle, view-scoped (with chip), free. Stores history in
st.session_state per page key so each page gets its own thread (per W11
+ USER_FLOW §A step 8: "fresh thread per page, no carry-over context").
"""

from __future__ import annotations

import streamlit as st

from app.llm import agent, privacy as priv_mod
from app.llm.prompts import context_header
from .citation_chip import citation_chip


def _thread_key(page: str) -> str:
    return f"chat_thread::{page}"


def chat_panel(page: str, context_params: dict | None = None, height: int = 600) -> None:
    """Render the chat panel for the given page."""
    thread_key = _thread_key(page)
    if thread_key not in st.session_state:
        st.session_state[thread_key] = []

    st.markdown("### Chat")
    if not agent.llm_enabled():
        st.info(
            "Chat disabled. Set `ANTHROPIC_API_KEY` and reload to enable.\n\n"
            "Per `docs/USER_FLOW.md` W5: dashboard works fully without the LLM."
        )
        return

    # Context chip
    if context_params:
        chip_label = context_header(page, context_params)
        if chip_label:
            cols = st.columns([5, 1])
            cols[0].caption(chip_label)
            if cols[1].button("✕", key=f"clear_ctx::{page}", help="Clear context"):
                # Remove the page param so the chip disappears on next render
                if "page" in st.query_params:
                    st.query_params.clear()
                    st.query_params["page"] = page
                st.rerun()

    # Render history
    container = st.container(height=height)
    with container:
        for i, msg in enumerate(st.session_state[thread_key]):
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg["role"] == "assistant":
                    if msg.get("refused"):
                        st.error(msg.get("refusal_reason") or "Blocked.")
                    if msg.get("error"):
                        st.error(msg["error"])
                    cites = msg.get("citations") or []
                    if cites:
                        st.caption("Sources:")
                        for j, c in enumerate(cites):
                            citation_chip(
                                c["tool"], c.get("args") or {}, c.get("n_rows", 0),
                                key=f"cite::{page}::{i}::{j}",
                            )

    # Input
    user_msg = st.chat_input("Ask about your data...", key=f"chat_input::{page}")
    if user_msg:
        # Append the context header to the FIRST user message of a fresh thread
        send_text = user_msg
        if context_params and not st.session_state[thread_key]:
            ctx = context_header(page, context_params)
            if ctx:
                send_text = f"{ctx}\n\n{user_msg}"

        st.session_state[thread_key].append({"role": "user", "content": user_msg})

        # Build history for API (only role+content). For now we don't carry
        # prior tool_use blocks across user-visible turns — each user-visible
        # turn re-runs the loop fresh. This is conservative and aligns with
        # USER_FLOW §A: simple, no long-term memory.
        with st.spinner("thinking..."):
            response = agent.run(
                send_text,
                history=None,
                privacy=priv_mod.PrivacyFilter.from_default(),
            )
        st.session_state[thread_key].append(
            {
                "role": "assistant",
                "content": response.text or "(no response)",
                "citations": response.citations,
                "refused": response.refused,
                "refusal_reason": response.refusal_reason,
                "error": response.error,
            }
        )
        st.rerun()
