"""Pedigree-derived priors for top-killer conditions.

For each target condition, count first-degree relatives affected and the
median age-at-onset (if recorded). Emit deterministic `risk_scores` rows.

First-degree = parents, full siblings, children. We match by `relationship`
string from the `pedigree` table (relationship-coded only, no names — per
docs/SCHEMA.md §5).

Condition strings are matched case-insensitively against a small dict of
synonyms. The `pedigree_conditions.condition` field is free text and the
data quality starts low; we deliberately accept broad matches and record
which person_ids contributed in `inputs_json` for auditability.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from typing import Iterable


# ---------------------------------------------------------------------------
# Condition synonyms. Free-text -> canonical bucket.
# ---------------------------------------------------------------------------

CONDITION_BUCKETS: dict[str, set[str]] = {
    "cvd": {
        "cvd", "cardiovascular disease", "heart disease",
        "coronary artery disease", "cad", "myocardial infarction",
        "heart attack", "mi", "stroke", "cerebrovascular accident",
        "cva", "ischemic heart disease", "congestive heart failure", "chf",
    },
    "t2dm": {
        "t2dm", "type 2 diabetes", "diabetes type 2", "type ii diabetes",
        "diabetes", "diabetes mellitus", "dm2", "niddm",
    },
    "alzheimers": {
        "alzheimers", "alzheimer's", "alzheimer disease",
        "alzheimer's disease", "dementia", "senile dementia",
    },
    "breast_cancer": {
        "breast cancer", "breast carcinoma", "breast ca",
    },
    "prostate_cancer": {
        "prostate cancer", "prostate carcinoma", "prostate ca",
    },
    "colon_cancer": {
        "colon cancer", "colorectal cancer", "colon carcinoma",
        "colorectal carcinoma", "crc", "bowel cancer",
    },
    "kidney_disease": {
        "kidney disease", "chronic kidney disease", "ckd",
        "renal failure", "renal disease", "nephropathy",
    },
    "hypertension": {
        "hypertension", "high blood pressure", "htn",
    },
}


# Lowercase set of first-degree relationship strings. The genome agent
# emits these (per docs/SCHEMA.md §5 example: "paternal grandfather"). We
# pattern-match against canonical phrases.
FIRST_DEGREE = {
    "father", "mother", "parent",
    "brother", "sister", "sibling",
    "son", "daughter", "child",
}


def _is_first_degree(relationship: str | None) -> bool:
    if not relationship:
        return False
    r = relationship.lower().strip()
    # Exact match against canonical labels.
    if r in FIRST_DEGREE:
        return True
    # Also accept "half-brother"/"half-sister" as first-degree-ish? Standard
    # genetic-counseling practice is full sibs only. Stay conservative.
    return False


def _bucket(condition: str) -> str | None:
    c = (condition or "").strip().lower()
    for bucket, synonyms in CONDITION_BUCKETS.items():
        if c in synonyms:
            return bucket
        # Substring fallback for free-text notes (e.g. "MI at 58").
        for syn in synonyms:
            if syn in c:
                return bucket
    return None


# ---------------------------------------------------------------------------
# Data shapes.
# ---------------------------------------------------------------------------

@dataclass
class PedigreeRow:
    person_id: str
    relationship: str | None


@dataclass
class ConditionRow:
    person_id: str
    condition: str
    age_at_onset: int | None


@dataclass
class PedigreeScoreRow:
    score_id: str
    value: float
    inputs_json: str
    notes: str | None


# ---------------------------------------------------------------------------
# Compute.
# ---------------------------------------------------------------------------

def compute_pedigree_scores(
    pedigree: Iterable[PedigreeRow],
    conditions: Iterable[ConditionRow],
) -> tuple[list[PedigreeScoreRow], list[str]]:
    """For each target bucket emit two scores when data is present:

      - `family_<bucket>_first_degree` — count of first-degree relatives
        with the condition (raw integer, stored as REAL).
      - `family_<bucket>_first_degree_median_onset` — median age at onset
        across those relatives. Skipped if no ages recorded.

    Plus a derived flag-style score:
      - `family_<bucket>_first_degree_before_60` — count of first-degree
        relatives with onset < 60 (1 if any, 2 if >=2, 0 otherwise). This
        is the genetic-counselor convention.
    """
    warnings: list[str] = []
    pedigree_list = list(pedigree)
    conditions_list = list(conditions)

    if not pedigree_list:
        warnings.append("pedigree_priors: pedigree empty — skipping")
        return [], warnings
    if not conditions_list:
        warnings.append(
            "pedigree_priors: pedigree_conditions empty — skipping "
            "(annotate GEDCOM NOTE fields per VISION.md §2)"
        )
        return [], warnings

    rel_by_id: dict[str, str | None] = {
        p.person_id: p.relationship for p in pedigree_list
    }

    # Group conditions by bucket, restricted to first-degree relatives.
    affected: dict[str, list[ConditionRow]] = {b: [] for b in CONDITION_BUCKETS}
    for c in conditions_list:
        rel = rel_by_id.get(c.person_id)
        if not _is_first_degree(rel):
            continue
        bucket = _bucket(c.condition)
        if bucket is None:
            continue
        affected[bucket].append(c)

    rows: list[PedigreeScoreRow] = []
    for bucket, rels in affected.items():
        if not rels:
            continue

        # Distinct person_ids — one relative can have multiple notes.
        distinct = {}
        for r in rels:
            # Keep the row with the lowest known age_at_onset (most
            # informative for "before 60" cutoffs).
            cur = distinct.get(r.person_id)
            if cur is None:
                distinct[r.person_id] = r
            elif r.age_at_onset is not None and (
                cur.age_at_onset is None or r.age_at_onset < cur.age_at_onset
            ):
                distinct[r.person_id] = r
        relatives = list(distinct.values())
        ids = sorted(distinct.keys())

        # Count.
        count = len(relatives)
        rows.append(PedigreeScoreRow(
            score_id=f"family_{bucket}_first_degree",
            value=float(count),
            inputs_json=json.dumps({
                "bucket": bucket,
                "person_ids": ids,
                "relationships": sorted(
                    {rel_by_id.get(i, "?") or "?" for i in ids}
                ),
            }, sort_keys=True),
            notes=None,
        ))

        # Median onset.
        ages = [r.age_at_onset for r in relatives if r.age_at_onset is not None]
        if ages:
            rows.append(PedigreeScoreRow(
                score_id=f"family_{bucket}_first_degree_median_onset",
                value=float(statistics.median(ages)),
                inputs_json=json.dumps({
                    "bucket": bucket,
                    "ages": sorted(ages),
                    "person_ids": ids,
                }, sort_keys=True),
                notes=None,
            ))

        # Before-60 flag (count of relatives with onset < 60).
        early = [r for r in relatives if r.age_at_onset is not None and r.age_at_onset < 60]
        rows.append(PedigreeScoreRow(
            score_id=f"family_{bucket}_first_degree_before_60",
            value=float(len(early)),
            inputs_json=json.dumps({
                "bucket": bucket,
                "person_ids": sorted(r.person_id for r in early),
                "ages": sorted(r.age_at_onset for r in early),
            }, sort_keys=True),
            notes=None,
        ))

    return rows, warnings
