"""
Pattern C — YAML-driven gene-adjusted nutrient calculators.

Walks `analysis/calculators/*.yaml`, joins each calculator's SNP list to
the `snps` table, computes a target value, writes to `nutrient_targets`.

YAML schema (per VISION.md §3):

    nutrient: choline_mg
    base_rdi: 550
    sex_modifier: { female: 425, male: 550 }   # optional
    snps:
      - rsid: rs7946
        effect_allele: T
        increment_mg: 50
      - rsid: rs12325817
        effect_allele: G
        increment_mg: 100
    output_field: choline_target_mg            # optional, informational

Effect counting: per the genetics convention used in Masterjohn's choline
calc, the increment is applied PER effect allele (so a TT genotype on a
T-effect SNP adds 2 * increment_mg).

This is one of three places the dashboard touches `snps` — the others are
... actually, this is the ONLY place. And the result is a TARGET VALUE,
not a per-rsid output. No raw rsid ever leaves this layer.

Idempotent: DELETE all rows from `nutrient_targets`, then INSERT.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from app import db

CALCULATORS_DIR = Path(__file__).parent.parent.parent / "analysis" / "calculators"


@dataclass(frozen=True)
class CalcResult:
    nutrient: str
    target_value: float
    unit: str
    inputs: dict


def _count_effect_alleles(genotype: str, effect_allele: str) -> int:
    """Count how many copies of `effect_allele` appear in `genotype`."""
    if not genotype or not effect_allele:
        return 0
    return sum(1 for ch in genotype.upper() if ch == effect_allele.upper())


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _compute_one(cfg: dict, sex: Optional[str] = None) -> Optional[CalcResult]:
    """Compute a single calculator's result. Returns None if `snps` table
    is missing entirely."""
    nutrient = cfg.get("nutrient")
    if not nutrient:
        return None

    # Base RDI: sex modifier overrides base_rdi if both present
    base = cfg.get("base_rdi")
    sex_mod = cfg.get("sex_modifier") or {}
    if sex and sex in sex_mod:
        base = sex_mod[sex]
    if base is None:
        return None
    target = float(base)

    inputs: dict = {"base_rdi": float(base), "snps": [], "increments": {}}

    snps_cfg = cfg.get("snps") or []
    for snp_spec in snps_cfg:
        rsid = snp_spec.get("rsid")
        if not rsid:
            continue
        effect = snp_spec.get("effect_allele", "")
        increment = float(snp_spec.get("increment_mg") or snp_spec.get("increment") or 0.0)
        # Look up the user's genotype
        df = db.read_sql_safe("SELECT genotype FROM snps WHERE rsid = ?", (rsid,))
        if df.empty:
            # Missing SNP — record it but contribute 0
            inputs["snps"].append({"rsid": rsid, "genotype": None, "n_effect": 0})
            continue
        genotype = str(df.iloc[0]["genotype"])
        n_effect = _count_effect_alleles(genotype, effect)
        contribution = n_effect * increment
        target += contribution
        inputs["snps"].append({"rsid": rsid, "genotype": genotype, "n_effect": n_effect})
        inputs["increments"][rsid] = contribution

    unit = "mg"
    if "_g" in str(nutrient) and "_mg" not in str(nutrient):
        unit = "g"

    return CalcResult(
        nutrient=str(nutrient),
        target_value=target,
        unit=unit,
        inputs=inputs,
    )


def run(sex: Optional[str] = None) -> list[CalcResult]:
    """Run every calculator under `analysis/calculators/` and write to
    `nutrient_targets`. Returns the list of computed results (or an empty
    list if there are no calculators)."""
    if not CALCULATORS_DIR.exists():
        return []

    results: list[CalcResult] = []
    for yaml_path in sorted(CALCULATORS_DIR.glob("*.yaml")):
        try:
            cfg = _load_yaml(yaml_path)
        except yaml.YAMLError:
            continue
        r = _compute_one(cfg, sex=sex)
        if r is not None:
            results.append(r)

    if not results:
        return []

    # Write to nutrient_targets (idempotent: DELETE + INSERT)
    con = db.open_rw()
    try:
        # If the table doesn't exist (schema not loaded), bail out cleanly.
        cur = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='nutrient_targets'"
        )
        if cur.fetchone() is None:
            return results
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        con.execute("DELETE FROM nutrient_targets")
        for r in results:
            con.execute(
                "INSERT INTO nutrient_targets(nutrient, target_value, unit, computed_from_json, computed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (r.nutrient, r.target_value, r.unit, json.dumps(r.inputs), now),
            )
        con.commit()
    finally:
        con.close()

    return results
