"""PGS-lite — small curated polygenic score panel.

Stub. Reads weight files from `ingest/risk/pgs_weights/*.tsv` (one PGS
per file, with columns: rsid, effect_allele, effect_weight) and computes a
weighted dosage sum against the `snps` table.

# TODO PGS panel — see VISION.md §1
# Target scores (curated, well-validated):
#   - PGS000018  Coronary Artery Disease (CAD)
#   - PGS000036  Type 2 Diabetes (T2DM)
#   - PGS000334  Alzheimer's Disease
#   - PGS000004  Breast cancer
#   - PGS000028  Prostate cancer
#   - PGS000058  LDL cholesterol
#
# Implementation plan:
#   1. Download chosen scores from https://www.pgscatalog.org/ (harmonized
#      builds) into ingest/risk/pgs_weights/PGS00####.tsv.
#   2. For each weights file, load into a dict {rsid: (effect_allele, w)}.
#   3. Query `snps` for those rsids.
#   4. Score = sum_over_rsids( dosage(effect_allele, genotype) * w )
#      where dosage is 0/1/2 = count of effect alleles in genotype.
#   5. Write one risk_scores row per PGS with score_id='pgs_<id>',
#      source='pgs_catalog', percentile=NULL (need a reference population
#      distribution to set percentile — defer to a follow-up).
#
# Privacy rule (CLAUDE.md §8): rsids and genotypes NEVER leave this
# process. We read them locally and write only the scalar score back.

This file ships as a stub: it scans for weight TSVs, and if none are
present, returns an empty list of scores with a single warning.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


WEIGHTS_DIR = Path(__file__).parent / "pgs_weights"


@dataclass
class SnpRow:
    rsid: str
    genotype: str


@dataclass
class PgsScoreRow:
    score_id: str
    value: float
    inputs_json: str
    notes: str | None


def _dosage(genotype: str, effect_allele: str) -> int | None:
    """Count of the effect allele in a 2-base genotype like 'AG'.

    Returns 0/1/2 for valid biallelic calls; None for no-calls ('--', '00').
    """
    g = (genotype or "").upper().strip()
    if not g or g in {"--", "00", "NN"}:
        return None
    if len(g) != 2:
        return None
    return sum(1 for b in g if b == effect_allele.upper())


def compute_pgs_scores(snps: Iterable[SnpRow]) -> tuple[list[PgsScoreRow], list[str]]:
    warnings: list[str] = []
    snp_index: dict[str, str] = {s.rsid: s.genotype for s in snps}

    if not WEIGHTS_DIR.exists():
        warnings.append(
            "pgs_lite: no ingest/risk/pgs_weights/ directory — stub only. "
            "See pgs_lite.py docstring for the curated target panel."
        )
        return [], warnings

    weight_files = sorted(WEIGHTS_DIR.glob("*.tsv"))
    if not weight_files:
        warnings.append(
            "pgs_lite: 0 weight files in ingest/risk/pgs_weights/ — stub. "
            "Drop PGS00####.tsv files from pgscatalog.org to enable."
        )
        return [], warnings

    rows: list[PgsScoreRow] = []
    for wf in weight_files:
        score_id = f"pgs_{wf.stem.lower()}"
        total = 0.0
        n_used = 0
        n_missing = 0
        used_rsids: list[str] = []
        with wf.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for row in reader:
                rsid = row.get("rsid", "").strip()
                ea = row.get("effect_allele", "").strip()
                try:
                    w = float(row.get("effect_weight", ""))
                except ValueError:
                    continue
                gt = snp_index.get(rsid)
                if gt is None:
                    n_missing += 1
                    continue
                d = _dosage(gt, ea)
                if d is None:
                    n_missing += 1
                    continue
                total += d * w
                n_used += 1
                used_rsids.append(rsid)

        if n_used == 0:
            warnings.append(
                f"pgs_lite: {wf.name} — 0 rsids matched (missing={n_missing}); "
                "skipping"
            )
            continue

        import json
        inputs = {
            "score_file": wf.name,
            "n_rsids_used": n_used,
            "n_rsids_missing": n_missing,
            # Privacy: we record rsid *counts* in inputs_json. We do NOT
            # record genotypes. The rsid list itself stays local (this DB
            # is local), but is not sent anywhere — CLAUDE.md §8.
            "rsids_used": sorted(used_rsids),
        }
        rows.append(PgsScoreRow(
            score_id=score_id,
            value=round(total, 6),
            inputs_json=json.dumps(inputs, sort_keys=True),
            notes=f"raw weighted sum; percentile=NULL until reference distribution available",
        ))

    return rows, warnings
