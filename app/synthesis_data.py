"""
Synthesis data loader.

The dashboard reads from ``analysis/health.db`` (gitignored) when present.
Until ingests land, this module returns the documented findings from
``docs/`` analysis as a deterministic fallback so the page always renders.

When the schema agent and ingest agents land, rewrite ``load()`` to query
SQLite instead of returning constants. The shape of the returned dict is
the public contract used by ``app/views/synthesis.py``.

Numbers below are computed in prior analysis passes against the user's
real data; sources noted inline.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "analysis" / "health.db"


# --------------------------------------------------------------------- fallback

# Documented findings — sourced from prior synthesis pass against health.db.
# Each section maps 1:1 to a section in the dashboard view.

HEADLINE = {
    "verdict_top": "The cut is working.",
    "verdict_bottom": "Particle burden isn't budging.",
    "subtitle": (
        "One year of measured progress, one stubborn number, and a clear set of levers. "
        "Synthesizes 1,929 observations across bloodwork, nutrition, sleep, training, "
        "and family history."
    ),
    "this_week": (
        "Weight, glucose, ALT, and inflammation are all moving in the right direction. "
        "But ApoB and LDL-P barely moved despite the deficit — which means the next 6 weeks "
        "are about food composition (saturated fat down, fiber up, omega-3 up) rather than "
        "further calorie restriction."
    ),
}

KPIS = [
    {
        "label": "ApoB",
        "value": 100,
        "unit": "mg/dL",
        "delta": -5,
        "delta_label": "vs Oct '24",
        "target": "<60",
        "status": "priority",
        "gauge_pct": 90,
        "target_pct": 60,
    },
    {
        "label": "Fasting glucose",
        "value": 82,
        "unit": "mg/dL",
        "delta": -24,
        "delta_label": "vs 2015",
        "target": "70–99",
        "status": "improving",
        "gauge_pct": 30,
        "target_pct": None,
    },
    {
        "label": "Bodyweight",
        "value": 188,
        "unit": "lb",
        "delta": -8,
        "delta_label": "in 49 days",
        "target": "~185 (cut)",
        "status": "on plan",
        "gauge_pct": 55,
        "target_pct": None,
    },
    {
        "label": "hs-CRP",
        "value": 0.66,
        "unit": "mg/L",
        "delta": -0.52,
        "delta_label": "vs prior draw",
        "target": "<1.0",
        "status": "dropping",
        "gauge_pct": 22,
        "target_pct": None,
    },
]


# Multi-line metabolic trajectory: draw dates × metric values
METABOLIC_TRAJECTORY = {
    "labels": ["2015", "2023", "2024-10", "2025-10", "2025-11"],
    "series": [
        {"name": "Glucose (mg/dL)",       "data": [114, 106, None, None, 82]},
        {"name": "ALT (U/L)",             "data": [None, 50, None, None, 24]},
        {"name": "Triglycerides (mg/dL)", "data": [None, None, None, 64, 56]},
        {"name": "LDL-c (mg/dL)",         "data": [None, None, None, 154, 124]},
    ],
}


HDL_SPARK = {
    "labels": ["2015", "2023", "2024-10", "2025-10", "2025-11"],
    "values": [38, 52, 49, 49, 41],
}


# Nutrient adequacy during 49-day cut window (2025-10-02 → 2025-11-20).
NUTRIENT_ADEQUACY = [
    {"name": "Protein",   "mean": "110%", "pct": 110, "tier": "good"},
    {"name": "B12",       "mean": "100%", "pct": 100, "tier": "good"},
    {"name": "Magnesium", "mean": "88%",  "pct": 88,  "tier": "watch"},
    {"name": "Vitamin D", "mean": "12.2 / 15 mcg · 81%", "pct": 81, "tier": "watch"},
    {"name": "Choline",   "mean": "411 / 550 mg · 75%",  "pct": 75, "tier": "watch"},
    {"name": "Calcium",   "mean": "600 / 1000 mg · 60%", "pct": 60, "tier": "watch"},
    {"name": "Fiber",     "mean": "14.5 / 38 g · 38%",   "pct": 38, "tier": "alert"},
    {"name": "Omega-3",   "mean": "0.4 / 1.6 g · 25%",   "pct": 25, "tier": "alert"},
]


SLEEP_STATS = {
    "mean_score": 73.6,
    "mean_duration_h": 7.6,
    "mean_duration_label": "7h 36m",
    "poor_pct": 30,
    "n_weeks": 86,
    "ends": "2025-01-16",
    "stale_days": 487,
    "histogram": {
        "labels": ["<60", "60-65", "65-70", "70-75", "75-80", "80-85", "85+"],
        "values": [3, 8, 15, 25, 22, 11, 2],
    },
}


# Decade-scale wins for the "four-win" panel
FOUR_WINS = [
    {"label": "Fasting glucose", "before": 114, "after": 82,  "change_pct": -28, "note": "pre-diabetic edge cleared"},
    {"label": "Liver ALT",       "before": 50,  "after": 24,  "change_pct": -52, "note": "fatty-liver proxy down"},
    {"label": "hs-CRP",          "before": 1.18, "after": 0.66, "change_pct": -44, "note": "low-risk zone"},
    {"label": "LDL-c",           "before": 154, "after": 124, "change_pct": -19, "note": "still above optimal"},
]


FAMILY_LONGEVITY = {
    "median_age": 78,
    "n_entities": 574,
    "n_edges": 611,
    "paternal_complete": True,
    "maternal_complete": True,
    "causes_annotated": False,
}


OUTCOMES = [
    {"n": "①", "title": "Cardiovascular risk",      "state": "live",  "tier": "priority", "note": "ApoB 100, LDL-P 1022, Lp(a) 6.4 (low). Monthly cadence."},
    {"n": "②", "title": "Metabolic resilience",     "state": "live",  "tier": "good",     "note": "Glucose 82, ALT 24. HbA1c next draw completes the picture."},
    {"n": "③", "title": "Body composition",         "state": "live",  "tier": "good",     "note": "188 lb, DEXA fat 23.3% (Oct 2025). Daily weight would tighten this."},
    {"n": "④", "title": "Strength progression",     "state": "paused","tier": "watch",    "note": "Lift logging stopped 2025-10-20. Resume for week-over-week trend."},
    {"n": "⑤", "title": "Sleep sufficiency",        "state": "stale", "tier": "watch",    "note": "86 weekly aggregates, ends 2025-01. Daily data unlocks 6 insights."},
    {"n": "⑥", "title": "Micronutrient sufficiency","state": "live",  "tier": "watch",    "note": "5 of 10 nutrients below target. Personalized targets pending genome."},
    {"n": "⑦", "title": "CBC drift detection",      "state": "live",  "tier": "good",     "note": "Background watchdog. Nothing to flag."},
    {"n": "⑧", "title": "Renal & hepatic",          "state": "live",  "tier": "good",     "note": "eGFR, BUN, ALT, AST within normal. Boring by design."},
    {"n": "⑨", "title": "Inflammation & immune",    "state": "live",  "tier": "good",     "note": "hs-CRP 0.66 (low). Eosinophil/NLR within normal."},
    {"n": "⑩", "title": "Genetic risk synthesis",   "state": "blocked","tier": "gap",     "note": "AncestryDNA + Promethease on disk. Privacy-gated ingest pending."},
    {"n": "⑪", "title": "Family-history priors",    "state": "blocked","tier": "gap",     "note": "574 entities mapped. 20-min annotation pass unlocks priors."},
    {"n": "⑫", "title": "Preventive screening",     "state": "blocked","tier": "gap",     "note": "Source file present. Parser pending."},
    {"n": "⑬", "title": "Weekly anomaly digest",    "state": "live",  "tier": "info",     "note": "Reads from every tile, surfaces ≤5 changes per week."},
]


ROADMAP = [
    {
        "tier": "1",
        "title": "Low effort",
        "items": [
            "Re-parse bloodwork CSV panel-aware",
            "Re-parse nutrition CSV with full 60 columns (SFA, caffeine, alcohol)",
            "Parse 2022 DEXA → 3-point body-comp trajectory",
        ],
        "unlocks": "ApoB attribution, late-eating insight, lean-mass partition.",
    },
    {
        "tier": "2",
        "title": "Privacy-sensitive",
        "items": [
            "AncestryDNA → curated 200-SNP variants table",
            "Promethease HTML → annotations table",
            "Choline calculator → personalized target",
        ],
        "unlocks": "10 genome-gated insights. Hashed/bucketed before any cloud call.",
    },
    {
        "tier": "3",
        "title": "With user",
        "items": [
            "20-min cause-of-death annotation pass",
            "Resume daily sleep logging",
            "Resume lift logging",
        ],
        "unlocks": "Family-history priors, sleep × everything, training trend.",
    },
]


# --------------------------------------------------------------------- public API

@dataclass
class SynthesisData:
    source: str  # "db" or "documented_fallback"
    db_path: Path | None
    headline: dict
    kpis: list[dict]
    metabolic: dict
    hdl: dict
    nutrients: list[dict]
    sleep: dict
    four_wins: list[dict]
    family: dict
    outcomes: list[dict]
    roadmap: list[dict]


def _try_db_load() -> SynthesisData | None:
    """Probe ``analysis/health.db`` and return a SynthesisData if the
    expected tables are present. Returns None if any required table is
    missing — caller falls back to documented constants.

    Stub: schema agent hasn't landed yet. Wire this up once the agreed
    tables exist (see docs/ORCHESTRATION.md).
    """
    if not DB_PATH.exists():
        return None
    try:
        with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as conn:
            tables = {
                r[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        required = {"labs", "nutrition_daily", "sleep", "lifts", "body_comp", "pedigree"}
        if not required.issubset(tables):
            return None
    except sqlite3.Error:
        return None
    # When ingests land, replace this with real queries. For now we still
    # return the documented constants so the page renders consistently.
    return None


def load() -> SynthesisData:
    db_result = _try_db_load()
    if db_result is not None:
        return db_result
    return SynthesisData(
        source="documented_fallback",
        db_path=DB_PATH if DB_PATH.exists() else None,
        headline=HEADLINE,
        kpis=KPIS,
        metabolic=METABOLIC_TRAJECTORY,
        hdl=HDL_SPARK,
        nutrients=NUTRIENT_ADEQUACY,
        sleep=SLEEP_STATS,
        four_wins=FOUR_WINS,
        family=FAMILY_LONGEVITY,
        outcomes=OUTCOMES,
        roadmap=ROADMAP,
    )
