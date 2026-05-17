"""Parse the Masterjohn Genetic Choline Calculator HTML export -> traits rows.

Source: w_data/Genetic Choline Calculator Results.html

The HTML has a 'profile' tab with a table of SNPs (rsID, call, variant
allele, gene, variation, +/+ +/- -/- result) plus three numeric scores
(SLC19A1, MTHFD1, MTHFR) and a combined methylfolate score. We emit:

  - one trait row per SNP in the report (kind = masterjohn_call_<rsid>)
  - one trait row for each score (numeric value as string, category=choline)
  - one trait row for the egg-yolk recommendation extracted from the text

This complements parse_ancestry: AncestryDNA gives us the raw genotype,
Masterjohn gives us a vetted human-readable interpretation we can show in
the dashboard without rolling our own choline model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from ingest.genome.parse_ancestry import TraitRow


@dataclass
class CholineSnp:
    rsid: str
    call: str  # raw 2-letter call as reported (e.g. "AG")
    variant_allele: str
    gene: str
    variation: str
    result: str  # one of "+/+", "+/-", "-/-"


class _CholineTableParser(HTMLParser):
    """Pulls rows out of the single <table id="mytable"> in the report."""

    def __init__(self) -> None:
        super().__init__()
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cell_buf: list[str] = []
        self._row_cells: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "table" and a.get("id") == "mytable":
            self._in_table = True
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._row_cells = []
        elif self._in_row and tag in ("td", "th"):
            self._in_cell = True
            self._cell_buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_table:
            self._in_table = False
        elif tag == "tr" and self._in_row:
            self._in_row = False
            if self._row_cells:
                self.rows.append(self._row_cells)
        elif tag in ("td", "th") and self._in_cell:
            self._in_cell = False
            text = "".join(self._cell_buf).strip()
            self._row_cells.append(text)

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_buf.append(data)


def _extract_score(html: str, label: str) -> float | None:
    """Find e.g. 'MTHFR Score:</strong> 75% decrease' -> 75.0."""
    pat = re.compile(
        rf"{re.escape(label)}\s*Score:?\s*</strong>\s*([0-9.]+)\s*%",
        re.IGNORECASE,
    )
    m = pat.search(html)
    return float(m.group(1)) if m else None


def _extract_egg_yolks(html: str) -> int | None:
    """Pull the recommended egg-yolk-equivalent count out of the ingress."""
    m = re.search(
        r"choline available per day in\s*<b>\s*(\d+)\s*</b>\s*egg yolks",
        html,
        re.IGNORECASE,
    )
    return int(m.group(1)) if m else None


def parse_choline_html(path: Path, source_tag: str) -> list[TraitRow]:
    html = path.read_text(encoding="utf-8")

    parser = _CholineTableParser()
    parser.feed(html)

    # First row is header; skip rows without enough columns.
    snps: list[CholineSnp] = []
    for cells in parser.rows[1:]:
        if len(cells) < 6:
            continue
        rsid = cells[0].strip()
        if not rsid.startswith("rs"):
            continue
        snps.append(
            CholineSnp(
                rsid=rsid,
                call=cells[1].strip(),
                variant_allele=cells[2].strip(),
                gene=cells[3].strip(),
                variation=cells[4].strip(),
                result=cells[5].strip(),
            )
        )

    traits: list[TraitRow] = []
    for s in snps:
        traits.append(
            TraitRow(
                trait=f"masterjohn_{s.gene.lower().replace('/', '_')}_{s.rsid}",
                category="choline",
                value=s.result,  # "+/+", "+/-", "-/-"
                source=source_tag,
                confidence=0.95,
                notes=f"{s.gene} {s.variation} call={s.call} variant={s.variant_allele}",
            )
        )

    # Numeric scores
    for label, trait_name in (
        ("SLC19A1", "masterjohn_slc19a1_score_pct"),
        ("MTHFD1", "masterjohn_mthfd1_score_pct"),
        ("MTHFR", "masterjohn_mthfr_score_pct"),
    ):
        score = _extract_score(html, label)
        if score is not None:
            traits.append(
                TraitRow(
                    trait=trait_name,
                    category="choline",
                    value=str(score),
                    source=source_tag,
                    confidence=0.95,
                    notes=f"{label} percent decrease (Masterjohn calculator)",
                )
            )

    # Combined methylfolate score - look near "Your Methylfolate Score:"
    m = re.search(
        r"Your Methylfolate Score:?\s*</strong>\s*([0-9.]+)\s*%",
        html,
        re.IGNORECASE,
    )
    if m:
        traits.append(
            TraitRow(
                trait="masterjohn_methylfolate_score_pct",
                category="choline",
                value=str(float(m.group(1))),
                source=source_tag,
                confidence=0.95,
                notes="Combined methylfolate score (Masterjohn calculator)",
            )
        )

    # Egg yolk recommendation
    yolks = _extract_egg_yolks(html)
    if yolks is not None:
        traits.append(
            TraitRow(
                trait="masterjohn_choline_egg_yolk_equivalents",
                category="choline",
                value=str(yolks),
                source=source_tag,
                confidence=0.9,
                notes=(
                    "Daily egg yolk equivalents (~136 mg choline each) "
                    "recommended by the Masterjohn calculator"
                ),
            )
        )

    return traits
