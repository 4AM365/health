"""
Nutrient-relevant SNP panel cross-reference.

Reads an AncestryDNA raw export (TSV: rsid, chromosome, position, allele1,
allele2) and reports genotype + literature-mapped interpretation for a curated
panel of variants with reasonable evidence for diet/nutrition relevance.

Each entry carries an evidence label (A=strong, B=moderate, C=exploratory).
Hypothesis-generating only -- not a diagnostic.

Usage:
    python scripts/snp_panel.py [path-to-AncestryDNA.txt]
"""

from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_DNA = Path("w_data/2024 Data/wc-dna-data-2024-05-31/AncestryDNA.txt")


PANEL = [
    {
        "rsid": "rs4988235",
        "gene": "LCT/MCM6",
        "label": "Lactase persistence (European)",
        "evidence": "A",
        "interp": {
            "TT": "Lactase-persistent (homozygous). Adult dairy tolerance.",
            "CT": "Lactase-persistent (heterozygous). Adult dairy tolerance.",
            "CC": "Lactase non-persistent. Likely lactose intolerance after weaning.",
        },
        "note": "Strongest known gene-diet selection in Europeans. Italians have lower T-allele frequency than Northern Europeans (~30-50% vs 70-90%).",
    },
    {
        "rsid": "rs182549",
        "gene": "MCM6",
        "label": "Lactase persistence (corroborating)",
        "evidence": "A",
        "interp": {
            "TT": "Lactase-persistent.",
            "CT": "Lactase-persistent.",
            "CC": "Lactase non-persistent.",
        },
        "note": "Tightly linked to rs4988235; should agree.",
    },
    {
        "rsid": "rs1801133",
        "gene": "MTHFR (C677T)",
        "label": "Folate metabolism",
        "evidence": "A",
        "interp": {
            "GG": "Wild type (CC), normal MTHFR activity.",
            "AG": "Heterozygous (CT), ~65% activity. Mildly elevated folate needs.",
            "AA": "Homozygous (TT), ~30% activity. Higher need for methylated folate; elevated homocysteine risk if low-folate diet.",
        },
        "note": "Allele coding: 23andMe/AncestryDNA report on +strand, so C677T appears as G/A.",
    },
    {
        "rsid": "rs1801131",
        "gene": "MTHFR (A1298C)",
        "label": "Folate metabolism (secondary)",
        "evidence": "B",
        "interp": {
            "TT": "Wild type (AA).",
            "GT": "Heterozygous (AC).",
            "GG": "Homozygous variant (CC). Mild MTHFR reduction.",
        },
        "note": "Compound heterozygous with C677T = stronger effect.",
    },
    {
        "rsid": "rs2236225",
        "gene": "MTHFD1 (G1958A)",
        "label": "Folate / formate metabolism",
        "evidence": "B",
        "interp": {
            "GG": "Wild type.",
            "AG": "Heterozygous. Slightly increased choline need.",
            "AA": "Homozygous variant. Higher choline requirement.",
        },
        "note": "Input to Masterjohn choline calculator.",
    },
    {
        "rsid": "rs7946",
        "gene": "PEMT",
        "label": "Endogenous choline synthesis",
        "evidence": "B",
        "interp": {
            "GG": "Wild type. Estrogen-driven PEMT works normally.",
            "AG": "Heterozygous. Mildly reduced endogenous choline synthesis; modestly higher dietary need.",
            "AA": "Homozygous variant. Substantially reduced PEMT activity; higher dietary choline need.",
        },
        "note": "Input to Masterjohn choline calculator.",
    },
    {
        "rsid": "rs762551",
        "gene": "CYP1A2",
        "label": "Caffeine metabolism rate",
        "evidence": "A",
        "interp": {
            "AA": "Fast metabolizer (*1A/*1A). Caffeine cleared quickly.",
            "AC": "Slow metabolizer. Higher CV risk at high intake.",
            "CC": "Slow metabolizer. Sensitive to caffeine.",
        },
        "note": "Slow metabolizers have elevated MI risk at >2-3 cups/day.",
    },
    {
        "rsid": "rs1229984",
        "gene": "ADH1B",
        "label": "Alcohol oxidation rate",
        "evidence": "A",
        "interp": {
            "GG": "Slow oxidation (typical European). Standard alcohol metabolism.",
            "AG": "Faster oxidation. Acetaldehyde flush possible.",
            "AA": "Fast oxidation. Strong flush; protective against alcoholism (rare in Europeans).",
        },
        "note": "Fast-oxidation variant is common in East Asians, rare in Europeans.",
    },
    {
        "rsid": "rs671",
        "gene": "ALDH2",
        "label": "Acetaldehyde clearance",
        "evidence": "A",
        "interp": {
            "GG": "Normal ALDH2.",
            "AG": "Reduced ALDH2 ('Asian flush'). Elevated esophageal cancer risk if drinking.",
            "AA": "Severely deficient. Drinking strongly contraindicated.",
        },
        "note": "Variant essentially absent in non-Asian populations.",
    },
    {
        "rsid": "rs429358",
        "gene": "APOE (1/2)",
        "label": "APOE haplotype site 1",
        "evidence": "A",
        "interp": {
            "TT": "Site 1: T/T (corresponds to e2 or e3).",
            "CT": "Site 1: C/T (one e4 allele present).",
            "CC": "Site 1: C/C (likely e4/e4).",
        },
        "note": "Combine with rs7412 to derive e2/e3/e4 haplotype.",
    },
    {
        "rsid": "rs7412",
        "gene": "APOE (2/2)",
        "label": "APOE haplotype site 2",
        "evidence": "A",
        "interp": {
            "CC": "Site 2: C/C (e3 or e4).",
            "CT": "Site 2: C/T (one e2 allele present).",
            "TT": "Site 2: T/T (e2/e2; rare).",
        },
        "note": "See APOE_haplotype line below for combined call.",
    },
    {
        "rsid": "rs9939609",
        "gene": "FTO",
        "label": "Obesity / appetite",
        "evidence": "A",
        "interp": {
            "TT": "Wild type. Lowest BMI association.",
            "AT": "Heterozygous. ~1.2 kg higher BMI on average.",
            "AA": "Homozygous risk. ~3 kg higher BMI on average; satiety dysregulation.",
        },
        "note": "Lifestyle attenuates risk substantially.",
    },
    {
        "rsid": "rs7903146",
        "gene": "TCF7L2",
        "label": "Type 2 diabetes risk",
        "evidence": "A",
        "interp": {
            "CC": "Wild type. Baseline T2D risk.",
            "CT": "Heterozygous. ~1.4x T2D risk.",
            "TT": "Homozygous. ~2x T2D risk; impaired insulin secretion.",
        },
        "note": "Strongest common T2D variant. Risk modifiable.",
    },
    {
        "rsid": "rs174537",
        "gene": "FADS1",
        "label": "ALA -> EPA/DHA conversion",
        "evidence": "B",
        "interp": {
            "GG": "Efficient ALA->EPA/DHA conversion (ancestral hunter-gatherer pattern).",
            "GT": "Intermediate conversion.",
            "TT": "Slower conversion. Higher direct EPA/DHA need.",
        },
        "note": "Selection in agricultural populations favored the T allele.",
    },
    {
        "rsid": "rs1800562",
        "gene": "HFE (C282Y)",
        "label": "Hereditary hemochromatosis",
        "evidence": "A",
        "interp": {
            "GG": "Wild type. No C282Y variant.",
            "AG": "Carrier. Mild iron-loading risk.",
            "AA": "Homozygous. Hereditary hemochromatosis risk.",
        },
        "note": "Highest penetrance HH variant.",
    },
    {
        "rsid": "rs1799945",
        "gene": "HFE (H63D)",
        "label": "Iron loading (secondary)",
        "evidence": "B",
        "interp": {
            "CC": "Wild type.",
            "CG": "Carrier. Mild iron-loading risk.",
            "GG": "Homozygous. Mild iron overload risk.",
        },
        "note": "Compound heterozygous with C282Y elevates risk further.",
    },
    {
        "rsid": "rs7501331",
        "gene": "BCMO1",
        "label": "Beta-carotene -> retinol conversion",
        "evidence": "B",
        "interp": {
            "CC": "Wild type. Efficient beta-carotene conversion.",
            "CT": "Heterozygous. ~30% reduced conversion.",
            "TT": "Homozygous. ~50% reduced conversion; benefits from preformed vitamin A.",
        },
        "note": "Relevant if relying on plant carotenoids for vitamin A.",
    },
    {
        "rsid": "rs1799930",
        "gene": "NAT2 (rs1799930)",
        "label": "Acetylation status (one tag site)",
        "evidence": "B",
        "interp": {
            "GG": "Wild type at this site.",
            "AG": "Variant. Contributes to slow-acetylator phenotype.",
            "AA": "Variant homozygous. Slow acetylator more likely.",
        },
        "note": "Slow acetylators handle aromatic amines (charred meat) less efficiently.",
    },
    {
        "rsid": "rs2228570",
        "gene": "VDR (FokI)",
        "label": "Vitamin D receptor function",
        "evidence": "C",
        "interp": {
            "GG": "F/F. Shorter VDR protein, often described as more active.",
            "AG": "F/f.",
            "AA": "f/f. Longer VDR; some studies link to lower bone density, modest effect.",
        },
        "note": "Evidence base mixed; vitamin D status itself matters more than VDR variant.",
    },
]


def load_dna(path: Path) -> dict[str, str]:
    genotypes: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or line.startswith("rsid"):
                continue
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) < 5:
                continue
            rsid = parts[0]
            a1, a2 = parts[3], parts[4]
            if not rsid.startswith("rs"):
                continue
            gt = "".join(sorted([a1.upper(), a2.upper()]))
            genotypes[rsid] = gt
    return genotypes


COMPLEMENT = {"A": "T", "T": "A", "C": "G", "G": "C"}


def revcomp_gt(gt: str) -> str:
    if not gt or len(gt) != 2 or not all(c in COMPLEMENT for c in gt):
        return gt
    return "".join(sorted(COMPLEMENT[c] for c in gt))


def lookup_interp(entry: dict, gt: str) -> tuple[str, str]:
    interp = entry["interp"]
    if gt in interp:
        return gt, interp[gt]
    rc = revcomp_gt(gt)
    if rc in interp:
        return f"{gt} (=>{rc} on +strand)", interp[rc]
    return gt, f"(no mapping for genotype '{gt}')"


def derive_apoe(rs429358: str | None, rs7412: str | None) -> str:
    if not rs429358 or not rs7412:
        return "(insufficient data)"
    s1 = rs429358
    s2 = rs7412
    if "0" in s1 or "0" in s2 or "-" in s1 or "-" in s2:
        return "(no-call)"
    pair = (s1, s2)
    table = {
        ("TT", "TT"): "e2/e2",
        ("TT", "CT"): "e2/e3",
        ("TT", "CC"): "e3/e3",
        ("CT", "CT"): "e2/e4",
        ("CT", "CC"): "e3/e4",
        ("CC", "CC"): "e4/e4",
        ("CT", "TT"): "e2/e4 (atypical)",
    }
    return table.get(pair, f"undetermined ({s1}/{s2})")


def main() -> None:
    dna_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DNA
    print(f"Loading {dna_path}...")
    geno = load_dna(dna_path)
    print(f"Loaded {len(geno):,} SNPs.\n")

    print(f"{'evid':<4}  {'rsid':<14}  {'gene':<22}  {'geno':<22}  interpretation")
    print("-" * 110)
    for entry in PANEL:
        gt = geno.get(entry["rsid"], "(missing)")
        if gt == "(missing)":
            interp = "(SNP not on this chip)"
            display = gt
        else:
            display, interp = lookup_interp(entry, gt)
        print(
            f"  {entry['evidence']}   {entry['rsid']:<14}  "
            f"{entry['gene']:<22}  {display:<22}  {interp}"
        )

    print()
    apoe = derive_apoe(geno.get("rs429358"), geno.get("rs7412"))
    print(f"APOE_haplotype (derived): {apoe}")
    print(
        "  e2: lower LDL, slightly higher TG.  "
        "e3/e3: most common, baseline.  "
        "e4: ~3-4x AD risk per allele, more LDL response to saturated fat."
    )

    print("\n--- Per-entry notes ---")
    for entry in PANEL:
        gt = geno.get(entry["rsid"], "(missing)")
        print(f"  [{entry['evidence']}] {entry['gene']} ({entry['rsid']}, geno {gt}): {entry['note']}")


if __name__ == "__main__":
    main()
