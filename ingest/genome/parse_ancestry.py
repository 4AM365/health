"""AncestryDNA raw export -> snps table.

We deliberately load ONLY the curated panel from snp_panel.yaml, NOT the
~700k SNPs in the raw file. SQLite query speed matters and the long tail
is analytically inert here. See CLAUDE.md s4 (surgical) + s6 (use code).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class PanelEntry:
    rsid: str
    gene: str
    category: str
    evidence: str
    why_we_care: str


def load_panel(panel_path: Path) -> list[PanelEntry]:
    """Read snp_panel.yaml -> list of PanelEntry."""
    data = yaml.safe_load(panel_path.read_text(encoding="utf-8"))
    panel = data.get("panel") or []
    return [
        PanelEntry(
            rsid=row["rsid"],
            gene=row["gene"],
            category=row["category"],
            evidence=row["evidence"],
            why_we_care=row["why_we_care"],
        )
        for row in panel
    ]


@dataclass
class SnpRow:
    rsid: str
    chromosome: str
    position: int
    genotype: str  # sorted-allele string, e.g. "AG", or "--" for no-call
    source: str


def parse_ancestry_for_panel(
    ancestry_path: Path, panel_rsids: set[str], source_tag: str
) -> list[SnpRow]:
    """Stream the AncestryDNA file. Emit one SnpRow per panel rsid found.

    Format: tab-delimited, header `rsid chromosome position allele1 allele2`,
    comments begin with '#'. Genotypes on the + strand. AncestryDNA uses
    '0' for no-calls.
    """
    found: dict[str, SnpRow] = {}
    panel_size = len(panel_rsids)

    with ancestry_path.open(encoding="utf-8") as f:
        for raw in f:
            if raw.startswith("#"):
                continue
            line = raw.rstrip("\r\n")
            if not line or line.startswith("rsid"):
                continue
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            rsid = parts[0]
            if rsid not in panel_rsids:
                continue
            chrom = parts[1]
            try:
                position = int(parts[2])
            except ValueError:
                position = 0
            a1 = parts[3].upper()
            a2 = parts[4].upper()
            if a1 == "0" or a2 == "0":
                gt = "--"
            else:
                gt = "".join(sorted([a1, a2]))
            found[rsid] = SnpRow(
                rsid=rsid,
                chromosome=chrom,
                position=position,
                genotype=gt,
                source=source_tag,
            )
            if len(found) == panel_size:
                # Early exit: we've found every rsid in the panel.
                break

    return list(found.values())


# --- Trait derivation from panel genotypes -------------------------------
#
# Maps a (rsid, sorted-genotype) pair to a derived-trait row. This is the
# bridge that lets the LLM (which can only see `traits`) get a useful
# signal from the genome without ever touching raw `snps`.

COMPLEMENT = {"A": "T", "T": "A", "C": "G", "G": "C"}


def revcomp(gt: str) -> str:
    if len(gt) != 2 or not all(c in COMPLEMENT for c in gt):
        return gt
    return "".join(sorted(COMPLEMENT[c] for c in gt))


# Per-rsid trait interpretation table. Values are
#   {sorted_genotype: (trait_value_label, confidence)}
# Confidence is a soft float in [0, 1] reflecting our certainty in the
# *call*, not in the downstream clinical effect (that's gene-level).
TRAIT_INTERP: dict[str, dict[str, tuple[str, float]]] = {
    "rs4988235": {
        "TT": ("lactase_persistent", 0.95),
        "CT": ("lactase_persistent", 0.95),
        "CC": ("lactase_non_persistent", 0.95),
    },
    "rs182549": {
        "TT": ("lactase_persistent", 0.9),
        "CT": ("lactase_persistent", 0.9),
        "CC": ("lactase_non_persistent", 0.9),
    },
    "rs1801133": {
        "GG": ("mthfr_677_wild", 0.95),
        "AG": ("mthfr_677_het", 0.95),
        "AA": ("mthfr_677_hom", 0.95),
    },
    "rs1801131": {
        "TT": ("mthfr_1298_wild", 0.9),
        "GT": ("mthfr_1298_het", 0.9),
        "GG": ("mthfr_1298_hom", 0.9),
    },
    "rs2236225": {
        "GG": ("mthfd1_wild", 0.9),
        "AG": ("mthfd1_het", 0.9),
        "AA": ("mthfd1_hom", 0.9),
    },
    "rs1051266": {
        "CC": ("slc19a1_wild", 0.85),
        "CT": ("slc19a1_het", 0.85),
        "TT": ("slc19a1_hom", 0.85),
    },
    "rs7946": {
        "GG": ("pemt_wild", 0.9),
        "AG": ("pemt_het", 0.9),
        "AA": ("pemt_hom", 0.9),
    },
    "rs762551": {
        "AA": ("caffeine_fast_metabolizer", 0.9),
        "AC": ("caffeine_slow_metabolizer", 0.9),
        "CC": ("caffeine_slow_metabolizer", 0.9),
    },
    "rs1229984": {
        "GG": ("adh1b_slow_oxidizer", 0.9),
        "AG": ("adh1b_fast_oxidizer", 0.9),
        "AA": ("adh1b_fast_oxidizer", 0.9),
    },
    "rs671": {
        "GG": ("aldh2_normal", 0.95),
        "AG": ("aldh2_reduced", 0.95),
        "AA": ("aldh2_deficient", 0.95),
    },
    "rs9939609": {
        "TT": ("fto_low_bmi_risk", 0.9),
        "AT": ("fto_intermediate_bmi_risk", 0.9),
        "AA": ("fto_high_bmi_risk", 0.9),
    },
    "rs7903146": {
        "CC": ("tcf7l2_low_t2d_risk", 0.9),
        "CT": ("tcf7l2_intermediate_t2d_risk", 0.9),
        "TT": ("tcf7l2_high_t2d_risk", 0.9),
    },
    "rs174537": {
        "GG": ("fads1_efficient", 0.85),
        "GT": ("fads1_intermediate", 0.85),
        "TT": ("fads1_slow", 0.85),
    },
    "rs1800562": {
        "GG": ("hfe_c282y_wild", 0.95),
        "AG": ("hfe_c282y_carrier", 0.95),
        "AA": ("hfe_c282y_hom", 0.95),
    },
    "rs1799945": {
        "CC": ("hfe_h63d_wild", 0.9),
        "CG": ("hfe_h63d_carrier", 0.9),
        "GG": ("hfe_h63d_hom", 0.9),
    },
    "rs7501331": {
        "CC": ("bcmo1_efficient", 0.85),
        "CT": ("bcmo1_intermediate", 0.85),
        "TT": ("bcmo1_slow", 0.85),
    },
    "rs1799930": {
        "GG": ("nat2_fast_acetylator_tag", 0.7),
        "AG": ("nat2_intermediate_acetylator_tag", 0.7),
        "AA": ("nat2_slow_acetylator_tag", 0.7),
    },
    "rs2228570": {
        "GG": ("vdr_fok1_FF", 0.7),
        "AG": ("vdr_fok1_Ff", 0.7),
        "AA": ("vdr_fok1_ff", 0.7),
    },
    "rs10757278": {
        "AA": ("9p21_low_cad_risk", 0.85),
        "AG": ("9p21_intermediate_cad_risk", 0.85),
        "GG": ("9p21_high_cad_risk", 0.85),
    },
    "rs1333049": {
        "AA": ("9p21_low_cad_risk_tag2", 0.85),
        "AC": ("9p21_intermediate_cad_risk_tag2", 0.85),
        "CC": ("9p21_high_cad_risk_tag2", 0.85),
    },
}


# APOE epsilon haplotype derivation from rs429358 + rs7412.
# Both must be present; we return the haplotype string ("e3/e3" etc.).
# Per established + strand mapping:
#   e2: rs429358=T  rs7412=T
#   e3: rs429358=T  rs7412=C
#   e4: rs429358=C  rs7412=C
APOE_TABLE: dict[tuple[str, str], str] = {
    ("TT", "TT"): "e2/e2",
    ("TT", "CT"): "e2/e3",
    ("TT", "CC"): "e3/e3",
    ("CT", "CT"): "e2/e4",
    ("CT", "CC"): "e3/e4",
    ("CC", "CC"): "e4/e4",
    ("CT", "TT"): "e2/e4",  # atypical but possible
}


def derive_apoe(rs429358_gt: str | None, rs7412_gt: str | None) -> str | None:
    if not rs429358_gt or not rs7412_gt:
        return None
    if "-" in rs429358_gt or "-" in rs7412_gt:
        return None
    return APOE_TABLE.get((rs429358_gt, rs7412_gt))


@dataclass
class TraitRow:
    trait: str
    category: str
    value: str
    source: str
    confidence: float | None
    notes: str | None


def derive_traits_from_snps(
    snps: list[SnpRow], panel: list[PanelEntry], source_tag: str
) -> list[TraitRow]:
    """Walk the loaded snps, look up the interp table, emit traits."""
    by_rsid = {s.rsid: s for s in snps}
    cat_by_rsid = {p.rsid: p.category for p in panel}
    gene_by_rsid = {p.rsid: p.gene for p in panel}

    traits: list[TraitRow] = []
    for rsid, table in TRAIT_INTERP.items():
        snp = by_rsid.get(rsid)
        if not snp or snp.genotype == "--":
            continue
        gt = snp.genotype
        hit = table.get(gt)
        if hit is None:
            # Try reverse-complement (AncestryDNA reports +strand, but some
            # interp tables are documented on the opposite strand).
            hit = table.get(revcomp(gt))
        if hit is None:
            continue
        trait_name, conf = hit
        cat = cat_by_rsid.get(rsid, "unknown")
        gene = gene_by_rsid.get(rsid, "")
        # PK is (trait, source). Prefix with rsid so corroborating tags
        # (e.g. rs4988235 + rs182549 both -> lactase_persistent) don't collide.
        traits.append(
            TraitRow(
                trait=f"{rsid}_{trait_name}",
                category=cat,
                value=trait_name,
                source=source_tag,
                confidence=conf,
                notes=f"{gene} ({rsid})",
            )
        )

    # APOE haplotype is derived from two SNPs.
    rs429358 = by_rsid.get("rs429358")
    rs7412 = by_rsid.get("rs7412")
    apoe_call = derive_apoe(
        rs429358.genotype if rs429358 else None,
        rs7412.genotype if rs7412 else None,
    )
    if apoe_call:
        traits.append(
            TraitRow(
                trait="apoe_haplotype",
                category="lipids",
                value=apoe_call,
                source=source_tag,
                confidence=0.95,
                notes="Derived from rs429358 + rs7412",
            )
        )

    return traits
