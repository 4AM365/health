"""Canonical metric names + unit normalization for the labs table.

Conventions:
- Canonical metric names are short, lowercase snake_case (e.g. `hdl`, `ldl_p`).
- The unit column carries the unit string (normalized to lowercase ASCII when
  trivial — `mg/dl`, `mmol/l`, `ng/ml`, `nmol/l`, `umol/l`, `uiu/ml`, `pg`, `fl`).
- Aliases below are matched case-insensitively after stripping punctuation,
  collapsing whitespace, and removing trailing parentheticals like "(SGPT)".

Maintained by: bloodwork agent. See METRICS.md for the human-facing list.
"""
from __future__ import annotations

import re

# Alias -> canonical metric. Lowercased + collapsed before lookup.
_ALIASES: dict[str, str] = {
    # Lipid panel
    "total cholesterol": "total_cholesterol",
    "cholesterol total": "total_cholesterol",
    "triglycerides": "triglycerides",
    "hdl": "hdl",
    "hdl cholesterol": "hdl",
    "ldl": "ldl",
    "ldlc": "ldl",
    "ldl cholesterol": "ldl",
    "non hdl": "non_hdl_p",            # SpectraCell "Non HDL" is in nmol/L (particles)
    "non-hdl particles": "non_hdl_p",
    "non hdl cholesterol": "non_hdl_cholesterol",
    "non-hdl cholesterol": "non_hdl_cholesterol",
    "vldl": "vldl",
    # Lipoprotein particles (SpectraCell)
    "vldl particles": "vldl_p",
    "total ldl particles": "ldl_p",
    "total ldl particles ldl-p": "ldl_p",
    "non-hdl particles": "non_hdl_p",
    "remnant lipoprotein": "remnant_lipoprotein",
    "dense ldl iii": "dense_ldl_iii",
    "dense ldl iv": "dense_ldl_iv",
    "total hdl particles": "hdl_p",
    "total hdl": "hdl_p",
    "buoyant hdl 2b": "hdl_2b",
    # Vascular inflammation
    "insulin": "insulin",
    "hs-crp": "hs_crp",
    "lp a": "lpa",
    "lipoprotein a": "lpa",
    "apo b": "apo_b",
    "apolipoprotein b": "apo_b",
    "apo a1": "apo_a1",
    "apolipoprotein a1": "apo_a1",
    "homocysteine": "homocysteine",
    # Metabolic panel
    "glucose": "glucose",
    "bun": "bun",
    "creatinine": "creatinine",
    "bun/creatinine ratio": "bun_creatinine_ratio",
    "egfr": "egfr",
    "sodium": "sodium",
    "potassium": "potassium",
    "chloride": "chloride",
    "co2": "co2",
    "calcium": "calcium",
    "total protein": "total_protein",
    "albumin": "albumin",
    "globulin": "globulin",
    "a/g ratio": "ag_ratio",
    "total bilirubin": "total_bilirubin",
    "alkaline phosphatase": "alkaline_phosphatase",
    "ast": "ast",
    "alt": "alt",
    "alt sgpt": "alt",
    # CBC
    "auto wbc": "wbc",
    "wbc": "wbc",
    "hemoglobin": "hemoglobin",
    "rbc": "rbc",
    "hematocrit": "hematocrit",
    "mcv": "mcv",
    "mchc": "mchc",
    "mch": "mch",
    "rdw": "rdw",
    "platelets": "platelets",
    "mpv": "mpv",
    "lymphocytes relative": "lymphocytes_pct",
    "eosinophils relative": "eosinophils_pct",
    "neutrophils absolute": "neutrophils_abs",
    "monocytes absolute": "monocytes_abs",
    "basophils absolute": "basophils_abs",
    "immature grans absolute": "immature_grans_abs",
    "neutrophils relative": "neutrophils_pct",
    "monocytes relative": "monocytes_pct",
    "basophils relative": "basophils_pct",
    "lymphocytes absolute": "lymphocytes_abs",
    "eosinophils absolute": "eosinophils_abs",
    "immature granulocytes": "immature_granulocytes_pct",
    # Iron panel
    "iron": "iron",
    "tibc": "tibc",
    "ferritin": "ferritin",
    # Urinalysis (numeric components only — qualitative ones are skipped)
    "spec grav urine": "urine_spec_grav",
    "ph urine": "urine_ph",
    "urobilinogen ua": "urine_urobilinogen",
    # Aggregates we deliberately ignore (DEXA, bodyweight) — handled by body agent
    # Listed here so they get caught by the skip path with a clear reason.
}

# Canonical names that belong to other agents — skip with explanation.
_NOT_BLOODWORK: set[str] = {
    "bodyweight",
    "dexa_fat_pct",
    "dexa_visceral",
}

_NOT_BLOODWORK_ALIASES = {
    "bodyweight": "bodyweight",
    "dexa fat %": "dexa_fat_pct",
    "dexa fat pct": "dexa_fat_pct",
    "dexa visceral": "dexa_visceral",
}

# Qualitative urinalysis dipstick fields ("Negative", "Trace", etc.). The labs
# table is numeric-only, so we deliberately drop these with a clear reason.
_QUALITATIVE_LABELS = {
    "leukocytes",
    "protein ua",
    "glucose urine",
    "ketones",
    "occult blood ua",
    "bilirubin ua",
    "nitrite urine quant",
}

# SpectraCell narrative / non-data rows (footers, comments, derived counts).
_NARRATIVE_LABELS = {
    "metabolic syndrome traits",
}


def normalize_key(label: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace for alias lookup."""
    s = label.strip().lower()
    # Drop parenthetical detail like "ALT (SGPT)" -> "alt sgpt"
    s = s.replace("(", " ").replace(")", " ")
    # Common cosmetic punctuation
    s = s.replace(",", " ").replace(":", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def canonical_metric(label: str) -> tuple[str | None, str | None]:
    """Map a raw source label to (canonical_metric, skip_reason).

    Returns (metric, None) on success, (None, reason) when the label should be skipped.
    """
    if label is None or not str(label).strip():
        return None, "empty label"
    key = normalize_key(label)
    if key in _ALIASES:
        return _ALIASES[key], None
    if key in _NOT_BLOODWORK_ALIASES:
        return None, f"not a bloodwork metric ({_NOT_BLOODWORK_ALIASES[key]} — handled by body agent)"
    if key in _QUALITATIVE_LABELS:
        return None, "qualitative urinalysis (labs table is numeric-only)"
    if key in _NARRATIVE_LABELS:
        return None, "narrative / derived non-data row"
    return None, f"unrecognized metric label: {label!r}"


# ---------------------------------------------------------------------------
# Unit normalization
# ---------------------------------------------------------------------------

_UNIT_ALIASES: dict[str, str] = {
    "mg/dl": "mg/dL",
    "mg/dl.": "mg/dL",
    "ng/ml": "ng/mL",
    "nmol/l": "nmol/L",
    "umol/l": "umol/L",
    "µmol/l": "umol/L",
    "µmol/l": "umol/L",
    "mmol/l": "mmol/L",
    "uiu/ml": "uIU/mL",
    "µiu/ml": "uIU/mL",
    "µiu/ml": "uIU/mL",
    "ulu/ml": "uIU/mL",
    "ug/dl": "ug/dL",
    "mg/l": "mg/L",
    "g/dl": "g/dL",
    "k/mm3": "x10E3/uL",
    "x10e3/ul": "x10E3/uL",
    "x10e6/ul": "x10E6/uL",
    "pg": "pg",
    "fl": "fL",
    "%": "%",
}


def normalize_unit(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    key = s.lower()
    return _UNIT_ALIASES.get(key, s)


# ---------------------------------------------------------------------------
# Reference range parsing
# ---------------------------------------------------------------------------

_RANGE_DASH = re.compile(r"^\s*([\d.]+)\s*-\s*([\d.]+)\s*$")
_LT = re.compile(r"^\s*<\s*([\d.]+)\s*$")
_LE = re.compile(r"^\s*<=\s*([\d.]+)\s*$")
_GT = re.compile(r"^\s*>\s*([\d.]+)\s*$")
_GE = re.compile(r"^\s*>=\s*([\d.]+)\s*$")


def parse_range(raw: str | None) -> tuple[float | None, float | None]:
    """Parse a reference-range string. Returns (low, high). Either side may be None."""
    if raw is None:
        return (None, None)
    s = str(raw).strip()
    if not s:
        return (None, None)

    m = _RANGE_DASH.match(s)
    if m:
        return (float(m.group(1)), float(m.group(2)))
    m = _LT.match(s) or _LE.match(s)
    if m:
        return (None, float(m.group(1)))
    m = _GT.match(s) or _GE.match(s)
    if m:
        return (float(m.group(1)), None)
    return (None, None)
