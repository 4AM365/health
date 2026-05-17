"""
Pattern E — screening calendar overlay.

A small static table of age-anchored screenings (USPSTF-style, plus a few
genetics-aware additions like Lp(a) once-in-lifetime, APOE-flagged
cardiovascular). Joins user age (derived from a `traits` row keyed to birth
year, if available) to flag overdue screenings.

This is intentionally not authoritative — it's a prompt for "have you done
X yet?" Every flag ends with "discuss with provider".
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from app import db


@dataclass(frozen=True)
class Screening:
    name: str
    starts_age: int
    repeat_years: Optional[int]   # None = once in lifetime
    note: str


# Static catalog. Trim aggressively per CLAUDE.md §3 — only screenings Will
# would plausibly trigger in the next ~10 years.
CATALOG: list[Screening] = [
    Screening("Colonoscopy (USPSTF)",   45, 10, "USPSTF recommends from age 45; interval depends on findings."),
    Screening("DEXA (men, baseline)",   50, 5,  "Often deferred to 70 absent risk factors; you already have one."),
    Screening("Lp(a) (once)",            0, None, "Genetically determined; standard panel rarely includes it."),
    Screening("CAC (calcium score)",    40, 5,  "Especially if APOE ε4 or family CVD <60."),
    Screening("CMP + CBC + lipid panel",30, 1,  "Annual baseline labs."),
    Screening("Skin cancer screen",     40, 1,  "Especially for fair skin / family history."),
    Screening("Hearing test (baseline)",55, 5,  "Baseline + every 5y absent symptoms."),
    Screening("Vision (dilated)",       40, 2,  "More often after 60 or with family glaucoma history."),
]


def _infer_birth_year() -> Optional[int]:
    """Pull birth year from a `traits` row if available, else None.

    We don't store DOB anywhere else by design (CLAUDE.md §8 privacy). If
    the genome agent has written a `birth_year` trait, we use it.
    """
    df = db.read_sql_safe("SELECT value FROM traits WHERE trait = 'birth_year' LIMIT 1")
    if df.empty:
        return None
    try:
        return int(str(df.iloc[0]["value"]))
    except (TypeError, ValueError):
        return None


def overlay() -> pd.DataFrame:
    """Returns a DataFrame: name, recommended, last_done (if known), due_in_years.

    `last_done` is left null — no UI surface for "I had X on date Y" yet.
    When the events table gets `event_type='screening'`, we can join here.
    """
    birth_year = _infer_birth_year()
    today = dt.date.today()
    age = (today.year - birth_year) if birth_year else None

    # Try to pull screening events
    events = db.read_sql_safe(
        "SELECT date, summary FROM events WHERE domain = 'screening' OR event_type = 'screening'"
    )

    out_rows: list[dict] = []
    for sc in CATALOG:
        last_done = None
        if not events.empty:
            match = events[events["summary"].fillna("").str.contains(sc.name, case=False)]
            if not match.empty:
                last_done = str(match["date"].max())
        if age is not None:
            if age < sc.starts_age:
                status = "Future"
                due_in_years = sc.starts_age - age
            else:
                status = "Recommended"
                if last_done:
                    try:
                        last_year = int(last_done[:4])
                        if sc.repeat_years is not None and (today.year - last_year) >= sc.repeat_years:
                            status = "Overdue"
                            due_in_years = 0
                        else:
                            status = "Recent"
                            due_in_years = sc.repeat_years - (today.year - last_year) if sc.repeat_years else None
                    except (ValueError, TypeError):
                        due_in_years = None
                else:
                    status = "No record"
                    due_in_years = 0
        else:
            status = "Unknown (no birth year)"
            due_in_years = None
        out_rows.append({
            "name": sc.name,
            "starts_age": sc.starts_age,
            "repeat_years": sc.repeat_years,
            "status": status,
            "last_done": last_done,
            "due_in_years": due_in_years,
            "note": sc.note,
        })
    return pd.DataFrame(out_rows)
