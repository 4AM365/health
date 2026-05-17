"""
routing.py — map (tool_name, args) -> (page, query_params) per
docs/UI_STRUCTURE.md §4. Used by citation chips: clicking one switches the
main pane to the right page with filters applied.

Wargame W10 mitigation: if a tool's args reference a filter the destination
page hasn't implemented yet, the page renders unfiltered with a non-blocking
notice. The routing layer's job is just to forward the args — the view is
responsible for honoring them or surfacing a "not yet supported" hint.
"""

from __future__ import annotations

from typing import Any

# tool_name -> (page_slug, [arg_keys to forward as query params])
ROUTES: dict[str, tuple[str, list[str]]] = {
    "list_metrics":            ("labs", []),
    "get_lab_series":          ("labs", ["metric", "since", "until"]),
    "get_lab_window_summary":  ("labs", ["metric"]),
    "get_nutrition_window":    ("nutrition", ["days", "group_by"]),
    "get_body_composition":    ("body", ["view", "since"]),
    "get_lift_prs":            ("body", ["view", "lift"]),
    "get_sleep_window":        ("body", ["view", "days"]),
    "get_traits":              ("genome", ["category"]),
    "get_events":              ("timeline", ["since", "until"]),
    "correlate":               ("ask", []),  # correlations live in chat
}


def route(tool: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Map a tool call to (page, query_params).

    Unknown tools route to the Ask page with no params — they're chat-only.
    """
    if tool not in ROUTES:
        return ("ask", {})
    page, keys = ROUTES[tool]
    params = {k: args[k] for k in keys if k in args and args[k] is not None}
    return (page, params)


def supported_filters(page: str) -> set[str]:
    """What query params a page knows how to honor. Views read this to
    decide whether to show the W10 'filter not yet supported' notice."""
    return {
        "labs":      {"metric", "since", "until"},
        "nutrition": {"days", "group_by"},
        "body":      {"view", "since", "lift", "days"},
        "genome":    {"category"},
        "timeline":  {"since", "until"},
        "ask":       set(),
        "home":      set(),
        "sources":   set(),
    }.get(page, set())
