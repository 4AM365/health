"""
brief.py — Pattern G, the daily brief composer.

One call per day, cheap Haiku model, cached to analysis/brief_cache.json
so the same day's brief is reused across Streamlit refreshes.

Wargame W9: ALWAYS opens with a freshness statement when any source is
>7 days stale. The freshness probe is deterministic — the LLM only narrates.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import pandas as pd

from app import db
from .agent import BRIEF_MODEL, llm_enabled
from .prompts import SYSTEM_PROMPT
from .privacy import PrivacyFilter

CACHE_PATH = Path(__file__).parent.parent.parent / "analysis" / "brief_cache.json"
FRESHNESS_THRESHOLD_DAYS = 7


def _today_key() -> str:
    return dt.date.today().isoformat()


def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except OSError:
        pass


def freshness_report() -> tuple[str, bool]:
    """Returns (multi-line freshness summary, any_stale_flag)."""
    meta = db.ingest_meta()
    if meta.empty:
        return ("No ingests recorded; run `python -m ingest.<domain>` to populate.", True)
    today = dt.date.today()
    lines: list[str] = []
    any_stale = False
    for _, row in meta.iterrows():
        try:
            last = dt.datetime.fromisoformat(str(row["last_run"]).replace("Z", "")).date()
        except (ValueError, TypeError):
            lines.append(f"{row['source']}: unknown last run")
            any_stale = True
            continue
        days = (today - last).days
        flag = "OK"
        if days > FRESHNESS_THRESHOLD_DAYS:
            flag = f"STALE ({days}d)"
            any_stale = True
        lines.append(f"{row['source']}: {last.isoformat()} ({flag}, n_rows={row['n_rows']})")
    return ("\n".join(lines), any_stale)


def _gather_summary_facts() -> dict:
    """Deterministic facts to hand to the LLM. The narration layer never
    queries the DB itself."""
    facts: dict = {}
    # Last 30d nutrition aggregates
    nut = db.read_sql_safe(
        """
        SELECT AVG(kcal) AS kcal, AVG(protein_g) AS protein_g,
               AVG(carb_g) AS carb_g, AVG(fat_g) AS fat_g,
               AVG(fiber_g) AS fiber_g, COUNT(*) AS n_days
        FROM nutrition_daily WHERE date >= date('now','-30 days')
        """
    )
    if not nut.empty:
        facts["nutrition_30d_avg"] = nut.iloc[0].to_dict()

    # Last 30d sleep
    slp = db.read_sql_safe(
        "SELECT AVG(total_hr) AS total_hr, AVG(rem_hr) AS rem_hr, COUNT(*) AS n FROM sleep WHERE date >= date('now','-30 days')"
    )
    if not slp.empty:
        facts["sleep_30d_avg"] = slp.iloc[0].to_dict()

    # Top-3 lab metrics by recency, with delta_pct over 90 days
    top = db.read_sql_safe(
        """
        SELECT metric, value, date
        FROM labs WHERE id IN (
            SELECT MAX(id) FROM labs GROUP BY metric
        )
        ORDER BY date DESC LIMIT 12
        """
    )
    facts["recent_labs"] = top.to_dict(orient="records") if not top.empty else []

    # Last 5 events
    ev = db.read_sql_safe(
        "SELECT date, domain, event_type, summary FROM events ORDER BY date DESC LIMIT 5"
    )
    facts["recent_events"] = ev.to_dict(orient="records") if not ev.empty else []

    return facts


def daily_brief(force: bool = False) -> dict:
    """Return today's brief.

    Returns:
      {
        "date": "YYYY-MM-DD",
        "freshness_summary": "...",
        "any_stale": bool,
        "text": "...",          # narrative; may be empty if LLM disabled
        "llm_enabled": bool,
        "from_cache": bool,
      }
    """
    fresh, any_stale = freshness_report()
    cache = _load_cache()
    today = _today_key()

    if not force and today in cache:
        c = cache[today]
        c["freshness_summary"] = fresh  # always refresh this — it's deterministic
        c["any_stale"] = any_stale
        c["from_cache"] = True
        return c

    if not llm_enabled():
        out = {
            "date": today,
            "freshness_summary": fresh,
            "any_stale": any_stale,
            "text": "",
            "llm_enabled": False,
            "from_cache": False,
        }
        return out

    facts = _gather_summary_facts()
    privacy = PrivacyFilter.from_default()

    facts_text = json.dumps(facts, default=str, indent=2)
    user_prompt = (
        "Compose today's daily brief. Use ONLY the deterministic facts below — "
        "do not invent numbers or call tools. Open with the freshness statement "
        "if any source is stale. 4-6 sentences max. End with 'discuss with provider' "
        "if any medical-shaped claim is made.\n\n"
        f"Freshness:\n{fresh}\n\n"
        f"Facts:\n{facts_text}\n"
    )

    out_check = privacy.check(user_prompt)
    if not out_check.ok:
        return {
            "date": today,
            "freshness_summary": fresh,
            "any_stale": any_stale,
            "text": "",
            "llm_enabled": True,
            "from_cache": False,
            "error": out_check.reason,
        }

    # Direct call — no tool-use loop for the brief (Haiku, deterministic facts).
    try:
        import anthropic
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=BRIEF_MODEL,
            max_tokens=600,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text").strip()
    except Exception as e:  # noqa: BLE001
        return {
            "date": today,
            "freshness_summary": fresh,
            "any_stale": any_stale,
            "text": "",
            "llm_enabled": True,
            "from_cache": False,
            "error": f"API error: {e}",
        }

    # Inbound privacy check
    in_check = privacy.check(text)
    if not in_check.ok:
        return {
            "date": today,
            "freshness_summary": fresh,
            "any_stale": any_stale,
            "text": "",
            "llm_enabled": True,
            "from_cache": False,
            "error": "brief blocked by inbound privacy filter",
        }

    out = {
        "date": today,
        "freshness_summary": fresh,
        "any_stale": any_stale,
        "text": text,
        "llm_enabled": True,
        "from_cache": False,
    }
    cache[today] = {**out, "freshness_summary": "", "any_stale": False}  # cache w/o the live freshness
    _save_cache(cache)
    return out
