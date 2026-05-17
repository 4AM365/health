"""
Pattern D — pedigree priors.

Read `pedigree` + `pedigree_conditions`, return aggregate "what does your
family say about your X" signals. Anonymized to relationship-degree only
(per VISION.md §5 anonymize helper).

NOTE on privacy: this module reads `pedigree` (relationship-coded only;
no names) and `pedigree_conditions`. Its OUTPUT does not include names
either — only "paternal grandfather" style relationship strings.

The output of this module is what the dashboard `family.py` view renders
and what the LLM is allowed to see. The `get_traits` tool does not
include this data; if/when we surface pedigree priors to the LLM, it
will be through a dedicated `get_family_priors` tool with the same
relationship-only output shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from app import db

# First-degree relationships
FIRST_DEGREE = {"father", "mother", "brother", "sister", "son", "daughter"}
# Second-degree (rough)
SECOND_DEGREE = {
    "paternal grandfather", "paternal grandmother",
    "maternal grandfather", "maternal grandmother",
    "uncle", "aunt", "nephew", "niece", "half-brother", "half-sister",
}


@dataclass(frozen=True)
class ConditionPrior:
    condition: str
    n_first_degree: int
    n_second_degree: int
    earliest_age: Optional[int]
    relationships: tuple[str, ...]


def family_history_flags() -> pd.DataFrame:
    """Return per-condition counts at 1st/2nd degree, plus a 'flag'
    column for the genetic-counselor-style ">=2 1st-degree with X before
    age 60" rule.
    """
    cond = db.read_sql_safe(
        """
        SELECT pc.condition, pc.age_at_onset, p.relationship
        FROM pedigree_conditions pc
        JOIN pedigree p ON p.person_id = pc.person_id
        """
    )
    if cond.empty:
        return pd.DataFrame(columns=[
            "condition", "n_first_degree", "n_second_degree",
            "earliest_age", "relationships", "flag",
        ])

    out_rows: list[dict] = []
    for c, grp in cond.groupby("condition"):
        rels = [str(r).lower() for r in grp["relationship"].dropna().tolist()]
        first = sum(1 for r in rels if r in FIRST_DEGREE)
        second = sum(1 for r in rels if r in SECOND_DEGREE)
        ages = grp["age_at_onset"].dropna().tolist()
        earliest = int(min(ages)) if ages else None
        flag = first >= 2 and (earliest is not None and earliest < 60)
        out_rows.append({
            "condition": c,
            "n_first_degree": first,
            "n_second_degree": second,
            "earliest_age": earliest,
            "relationships": tuple(sorted(set(rels))),
            "flag": flag,
        })
    return pd.DataFrame(out_rows).sort_values(
        by=["flag", "n_first_degree", "n_second_degree"], ascending=[False, False, False]
    )


def cause_of_death_distribution() -> pd.DataFrame:
    """Cause-of-death counts by relationship-degree. Requires
    `pedigree.death_year` IS NOT NULL and a 'cause' condition linked to
    them (commonly 'cause of death: X').
    """
    df = db.read_sql_safe(
        """
        SELECT pc.condition, p.relationship, p.death_year, pc.age_at_onset
        FROM pedigree_conditions pc
        JOIN pedigree p ON p.person_id = pc.person_id
        WHERE p.death_year IS NOT NULL
        """
    )
    if df.empty:
        return pd.DataFrame(columns=["condition", "relationship", "n", "median_age_at_death"])
    return df.groupby(["condition", "relationship"]).agg(
        n=("condition", "count"),
        median_age_at_death=("age_at_onset", "median"),
    ).reset_index().sort_values(by="n", ascending=False)
