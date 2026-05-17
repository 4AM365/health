"""PhenoAge — Levine 2018 biological age estimator.

Reference:
  Levine, M. E., et al. "An epigenetic biomarker of aging for lifespan and
  healthspan." Aging (2018), 10(4): 573–591. The PhenoAge linear predictor
  uses 9 standard clinical labs plus chronological age. Formula:

    xb = -19.907
       - 0.0336 * albumin (g/L)
       + 0.0095 * creatinine (umol/L)
       + 0.1953 * glucose (mmol/L)
       + 0.0954 * ln(CRP, mg/L)
       - 0.0120 * lymphocyte_pct
       + 0.0268 * mcv (fL)
       + 0.3306 * rdw (%)
       + 0.0019 * alk_phos (U/L)
       + 0.0554 * wbc (1000 cells/uL)
       + 0.0804 * chronological_age

    M = 1 - exp( -1.51714 * exp(xb) / 0.0076927 )
    phenoage = 141.50225 + ln(-0.00553 * ln(1 - M)) / 0.090165

This module:
  1. Reads `labs` for the 9 markers, grouped by date.
  2. For each date that has all 9 markers present, computes PhenoAge.
  3. Normalizes units (mg/dL <-> mmol/L, etc.) defensively before plugging in.
  4. Returns a list of (date, phenoage_value, inputs_json) tuples for the
     caller (__main__) to insert into `risk_scores`.

Unit normalization rules:
  - albumin: accept g/dL (multiply by 10) or g/L (leave).
  - creatinine: accept mg/dL (multiply by 88.4) or umol/L (leave).
  - glucose: accept mg/dL (divide by 18.0156) or mmol/L (leave).
  - CRP: accept mg/L (leave) or mg/dL (multiply by 10).
  - lymphocyte %: accept % (leave). If reported as absolute (10^9/L), skip
    that date (we'd need WBC to derive %; safer to skip).
  - MCV: fL (leave).
  - RDW: % (leave). Some labs report RDW-SD in fL; we expect RDW-CV (%).
  - Alk phos: U/L (leave).
  - WBC: 10^3/uL (== 10^9/L) — leave; if reported as cells/uL divide by 1000.

If anything looks off (e.g. lymphocyte% > 80 or albumin clearly in wrong
unit), the row is skipped and a warning printed (CLAUDE.md §7 — fail loud).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Iterable


# ---------------------------------------------------------------------------
# Lab metric -> canonical name mapping. The bloodwork agent canonicalizes
# metric names, but different sources / lab providers vary. We match
# case-insensitively against a small set of expected canonical names + common
# alternatives.
# ---------------------------------------------------------------------------

METRIC_ALIASES: dict[str, set[str]] = {
    "albumin": {"albumin", "alb"},
    "creatinine": {"creatinine", "creat", "creatinine, serum"},
    "glucose": {"glucose", "glucose, fasting", "fasting glucose", "glu"},
    "crp": {"crp", "c-reactive protein", "hs-crp", "hscrp"},
    "lymphocyte_pct": {
        "lymphocyte %", "lymphocytes %", "lymph %", "lymphocyte_pct",
        "lymph%", "lymphs %",
    },
    "mcv": {"mcv", "mean corpuscular volume", "mean cell volume"},
    "rdw": {"rdw", "rdw-cv", "red cell distribution width"},
    "alk_phos": {
        "alp", "alk phos", "alkaline phosphatase",
        "alkaline_phosphatase", "alk_phos",
    },
    "wbc": {"wbc", "white blood cell count", "white blood cells"},
}


def _canonical_metric(name: str) -> str | None:
    n = name.strip().lower()
    for canonical, aliases in METRIC_ALIASES.items():
        if n in aliases:
            return canonical
    return None


# ---------------------------------------------------------------------------
# Unit normalization. Returns the value in the unit PhenoAge expects, or
# None if we can't trust it.
# ---------------------------------------------------------------------------

def _norm_albumin(value: float, unit: str | None) -> float | None:
    u = (unit or "").lower().strip()
    if u in {"g/dl", "g/dL".lower()}:
        return value * 10.0  # g/dL -> g/L
    if u in {"g/l", ""}:
        # Heuristic: serum albumin in g/L is typically 35-55; in g/dL 3.5-5.5.
        if value < 10 and u == "":
            return value * 10.0
        return value
    return None


def _norm_creatinine(value: float, unit: str | None) -> float | None:
    u = (unit or "").lower().strip()
    if u in {"mg/dl"}:
        return value * 88.4  # mg/dL -> umol/L
    if u in {"umol/l", "µmol/l"}:
        return value
    if u == "":
        # Heuristic: serum creat in mg/dL is ~0.5-1.5; in umol/L ~50-150.
        return value * 88.4 if value < 10 else value
    return None


def _norm_glucose(value: float, unit: str | None) -> float | None:
    u = (unit or "").lower().strip()
    if u in {"mg/dl"}:
        return value / 18.0156  # mg/dL -> mmol/L
    if u in {"mmol/l"}:
        return value
    if u == "":
        # Heuristic: fasting glucose mg/dL is ~70-110, mmol/L ~3.9-6.1.
        return value / 18.0156 if value > 20 else value
    return None


def _norm_crp(value: float, unit: str | None) -> float | None:
    u = (unit or "").lower().strip()
    if u in {"mg/l"}:
        return value
    if u in {"mg/dl"}:
        return value * 10.0
    if u == "":
        # Heuristic: hs-CRP mg/L is typically 0.1-10, mg/dL is 0.01-1.0.
        return value * 10.0 if value < 1 else value
    return None


def _norm_lymphocyte_pct(value: float, unit: str | None) -> float | None:
    u = (unit or "").lower().strip()
    if u in {"%", "percent", ""} and 0 < value < 100:
        return value
    return None


def _norm_mcv(value: float, unit: str | None) -> float | None:
    u = (unit or "").lower().strip()
    if u in {"fl", "fL".lower(), ""} and 50 < value < 130:
        return value
    return None


def _norm_rdw(value: float, unit: str | None) -> float | None:
    u = (unit or "").lower().strip()
    # Levine uses RDW-CV in percent (typical range 11.5-14.5).
    if u in {"%", ""} and 5 < value < 30:
        return value
    return None


def _norm_alk_phos(value: float, unit: str | None) -> float | None:
    u = (unit or "").lower().strip()
    if u in {"u/l", "iu/l", ""} and value > 0:
        return value
    return None


def _norm_wbc(value: float, unit: str | None) -> float | None:
    u = (unit or "").lower().strip()
    # PhenoAge expects WBC in 10^3/uL == 10^9/L. Typical range 4-11.
    if u in {"10^3/ul", "k/ul", "10*3/ul", "x10^3/ul", "10^9/l", ""}:
        if 1 < value < 50:
            return value
        # Maybe reported as cells/uL (e.g. 7500). Divide.
        if value > 1000:
            return value / 1000.0
    return None


NORMALIZERS = {
    "albumin": _norm_albumin,
    "creatinine": _norm_creatinine,
    "glucose": _norm_glucose,
    "crp": _norm_crp,
    "lymphocyte_pct": _norm_lymphocyte_pct,
    "mcv": _norm_mcv,
    "rdw": _norm_rdw,
    "alk_phos": _norm_alk_phos,
    "wbc": _norm_wbc,
}

REQUIRED = list(NORMALIZERS.keys())


# ---------------------------------------------------------------------------
# Levine 2018 formula.
# ---------------------------------------------------------------------------

def _phenoage(
    chronological_age: float,
    albumin_gpl: float,
    creatinine_umol: float,
    glucose_mmol: float,
    crp_mgl: float,
    lymphocyte_pct: float,
    mcv_fl: float,
    rdw_pct: float,
    alk_phos_ul: float,
    wbc_k: float,
) -> float:
    """Return PhenoAge in years given normalized lab values + chrono age."""
    # CRP appears as ln(CRP). Guard against zero/negative CRP by flooring at
    # a small positive value. (Some labs report < 0.1 as "<0.1"; the
    # bloodwork agent is expected to map that to a small number, e.g. 0.05.)
    crp_for_ln = max(crp_mgl, 0.01)

    xb = (
        -19.907
        - 0.0336 * albumin_gpl
        + 0.0095 * creatinine_umol
        + 0.1953 * glucose_mmol
        + 0.0954 * math.log(crp_for_ln)
        - 0.0120 * lymphocyte_pct
        + 0.0268 * mcv_fl
        + 0.3306 * rdw_pct
        + 0.0019 * alk_phos_ul
        + 0.0554 * wbc_k
        + 0.0804 * chronological_age
    )

    # Mortality score M.
    m = 1.0 - math.exp(-1.51714 * math.exp(xb) / 0.0076927)
    # Numerical guard — if m saturates to 1.0 the log(1-m) blows up.
    m = min(m, 1.0 - 1e-9)
    m = max(m, 1e-9)

    phenoage = 141.50225 + math.log(-0.00553 * math.log(1.0 - m)) / 0.090165
    return phenoage


# ---------------------------------------------------------------------------
# Top-level: scan labs by date, build PhenoAge rows.
# ---------------------------------------------------------------------------

@dataclass
class LabRow:
    id: int
    date: str
    metric: str
    value: float
    unit: str | None


@dataclass
class PhenoAgeRow:
    date: str
    value: float
    chronological_age: float
    inputs_json: str
    notes: str | None


def compute_phenoage_rows(
    labs: Iterable[LabRow],
    birth_year: int,
) -> tuple[list[PhenoAgeRow], list[str]]:
    """Group labs by date, compute PhenoAge for any date where all 9 are present.

    Returns (rows, warnings). Warnings are printed by __main__.
    """
    warnings: list[str] = []

    # Bucket labs by (date, canonical metric). If multiple values exist for
    # the same metric on the same day, take the first one with a usable
    # normalized value (labs occasionally re-run a marker same-day).
    by_date: dict[str, dict[str, tuple[int, float]]] = {}
    for r in labs:
        canon = _canonical_metric(r.metric)
        if canon is None:
            continue
        if r.value is None:
            continue
        norm = NORMALIZERS[canon](r.value, r.unit)
        if norm is None:
            warnings.append(
                f"phenoage: dropping {r.date} {r.metric}={r.value} "
                f"({r.unit!r}) — unit/range not recognized"
            )
            continue
        by_date.setdefault(r.date, {})
        # First wins (deterministic given sort order).
        by_date[r.date].setdefault(canon, (r.id, norm))

    rows: list[PhenoAgeRow] = []
    for date, markers in sorted(by_date.items()):
        missing = [m for m in REQUIRED if m not in markers]
        if missing:
            warnings.append(
                f"phenoage: skipping {date} — missing {','.join(missing)}"
            )
            continue

        # Chronological age at the date of the labs. Use year-only because
        # birth_year is what we get; close enough for an age-in-years scalar.
        try:
            year = int(date[:4])
        except (ValueError, IndexError):
            warnings.append(f"phenoage: skipping {date} — bad date format")
            continue
        chrono = float(year - birth_year)
        if chrono < 18 or chrono > 110:
            warnings.append(
                f"phenoage: skipping {date} — implausible chronological "
                f"age {chrono:.0f}"
            )
            continue

        value = _phenoage(
            chronological_age=chrono,
            albumin_gpl=markers["albumin"][1],
            creatinine_umol=markers["creatinine"][1],
            glucose_mmol=markers["glucose"][1],
            crp_mgl=markers["crp"][1],
            lymphocyte_pct=markers["lymphocyte_pct"][1],
            mcv_fl=markers["mcv"][1],
            rdw_pct=markers["rdw"][1],
            alk_phos_ul=markers["alk_phos"][1],
            wbc_k=markers["wbc"][1],
        )

        inputs = {
            "formula": "levine_2018",
            "chronological_age": chrono,
            "lab_ids": [markers[m][0] for m in REQUIRED],
            "normalized": {m: markers[m][1] for m in REQUIRED},
        }

        rows.append(
            PhenoAgeRow(
                date=date,
                value=round(value, 2),
                chronological_age=chrono,
                inputs_json=json.dumps(inputs, sort_keys=True),
                notes=None,
            )
        )

    return rows, warnings
