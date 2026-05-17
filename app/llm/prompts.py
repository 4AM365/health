"""
prompts.py — system prompt + per-view context headers per LLM_INTERFACE §5.

Wargame mitigations baked in:
- W4 (diagnosis): explicit "no diagnosis; end medical-shaped answers with
  'discuss with provider'".
- W3 (hallucination): "cite specific dates and values from tool results.
  Do not invent numbers."
- W1/W2 (genome privacy): "you never see raw genotypes or pedigree data.
  If the user asks for those, explain the constraint and offer a derived
  alternative."
- W8 (no write surface): tool names are all `get_*`/`list_*`/`correlate`;
  the system prompt also states "you have read-only tools."
"""

SYSTEM_PROMPT = """You are a personal-health analyst for one user. You have read-only tool access to their bloodwork, nutrition, body composition, sleep, lifts, and derived genome traits.

Rules:
- You have read-only tools. You cannot write to the database, edit files, or run ingests.
- Do not diagnose. End medical-shaped answers with "discuss with provider."
- Do not guess. Call a tool. If a tool returns no rows, say so plainly; do not invent.
- Cite specific dates and values from tool results. Do not invent numbers.
- You never see raw genotypes, raw rsids, or pedigree data. If the user asks for those, explain the constraint and offer a derived alternative (e.g., "ask about the *trait*, not the rsid").
- When a tool returns truncated:true, either re-call with a narrower window or tell the user to narrow.
- Insights here are pattern-matching, not medicine.
"""


def context_header(page: str, params: dict) -> str:
    """Per-view context chip rendered into the user message at chat start."""
    if not page or page == "ask":
        return ""
    bits: list[str] = []
    if page == "labs":
        if params.get("metric"):
            bits.append(f"metric={params['metric']}")
        if params.get("since"):
            bits.append(f"since={params['since']}")
        if params.get("until"):
            bits.append(f"until={params['until']}")
    elif page == "nutrition":
        if params.get("days"):
            bits.append(f"days={params['days']}")
    elif page == "body":
        if params.get("view"):
            bits.append(f"view={params['view']}")
    elif page == "genome":
        if params.get("category"):
            bits.append(f"category={params['category']}")
    suffix = ", " + ", ".join(bits) if bits else ""
    return f"[Context: viewing {page}{suffix}]"
