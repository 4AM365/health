"""citation_chip — small clickable chip below each LLM message.

Per UI_STRUCTURE.md §4: every numeric claim is backed by a chip; clicking
it navigates to the page filtered to those rows. We use st.query_params
+ st.experimental_set_query_params for cross-page deep-linking.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.routing import route, supported_filters


def citation_chip(tool: str, args: dict[str, Any], n_rows: int, key: str) -> None:
    """Render one chip. On click, set query params and rerun."""
    page, params = route(tool, args)
    label = f"{tool}({', '.join(f'{k}={v}' for k, v in args.items()) if args else ''}) · {n_rows} rows"
    if st.button(label, key=key, help=f"Open {page} filtered to {params}"):
        # Forward filters as query params and switch page
        new_params = {"page": page, **{k: str(v) for k, v in params.items()}}
        st.query_params.clear()
        for k, v in new_params.items():
            st.query_params[k] = v
        # Warn if any filter is unsupported (W10)
        unsupported = set(params) - supported_filters(page)
        if unsupported:
            st.warning(
                f"Page `{page}` does not yet support filters: "
                f"{sorted(unsupported)}. Showing unfiltered view."
            )
        st.rerun()
