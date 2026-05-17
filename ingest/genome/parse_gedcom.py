"""GEDCOM -> pedigree rows.

PRIVACY: names are dropped at the parser layer. The `pedigree` table never
stores names; only relationship codes like 'paternal_grandfather',
'maternal_aunt_3', 'sibling_1'. See CLAUDE.md s8 + AGENTS.md.

Source is in gitignored private/. If absent, this parser does nothing and
the caller logs a skip (CLAUDE.md s7 fail-loud).

We reuse the GEDCOM parsing logic from scripts/gedcom_stats.py rather than
re-implementing it.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

# Pull the parse_gedcom helper from the salvaged script.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from gedcom_stats import (  # type: ignore  # noqa: E402
    Family,
    Individual,
    ROOT_INDI,
    parse_gedcom,
)


@dataclass
class PedigreeRow:
    person_id: str
    relationship: str
    sex: str  # "M" / "F" / ""
    birth_year: int | None
    death_year: int | None
    source: str


# --- Relationship coding -------------------------------------------------
#
# We walk the ancestor graph from the root individual (Will). Each ancestor
# gets a relationship label derived purely from the path taken to reach
# them (sequence of F/M choices), never from their name.
#
# Examples:
#   gen 0:  "self"
#   gen 1:  "father", "mother"
#   gen 2:  "paternal_grandfather", "paternal_grandmother",
#           "maternal_grandfather", "maternal_grandmother"
#   gen 3+: "<paternal|maternal>_great<n>_grand<father|mother>"
#
# Siblings of ancestors (aunts/uncles) are labeled by their line:
#   "paternal_aunt_1", "maternal_uncle_2", etc., counted within line.
#
# Anyone reachable via spouse-only links (no blood) is dropped.


def _ancestor_label(path: list[str]) -> str:
    """`path` is a list like ['F', 'M', 'F'] from root to ancestor.
    Returns a stable relationship code based purely on path structure."""
    if not path:
        return "self"
    if len(path) == 1:
        return "father" if path[0] == "F" else "mother"
    line = "paternal" if path[0] == "F" else "maternal"
    final_sex = path[-1]
    final = "father" if final_sex == "F" else "mother"
    grand_depth = len(path) - 2  # 0 -> grand, 1 -> great-grand, 2 -> great-great-grand
    if grand_depth == 0:
        return f"{line}_grand{final}"
    if grand_depth == 1:
        return f"{line}_greatgrand{final}"
    # 2x-great and beyond -> "great<n>_grand..."
    return f"{line}_great{grand_depth}_grand{final}"


def _person_id_for(xref: str, source_tag: str) -> str:
    """Deterministic non-identifying id. We hash the xref so the same GEDCOM
    re-run produces stable ids without ever encoding a name."""
    h = hashlib.sha256(f"{source_tag}:{xref}".encode()).hexdigest()[:12]
    return f"ped_{h}"


def _walk_ancestors(
    root_xref: str,
    indis: dict[str, Individual],
    fams: dict[str, Family],
) -> dict[str, list[str]]:
    """BFS from root. For each ancestor xref, record the F/M path from root
    to that ancestor. If two paths exist, keep the first (BFS = shortest).
    Self maps to []."""
    paths: dict[str, list[str]] = {root_xref: []}
    queue: list[str] = [root_xref]
    while queue:
        x = queue.pop(0)
        indi = indis.get(x)
        if not indi or not indi.famc:
            continue
        fam = fams.get(indi.famc)
        if not fam:
            continue
        # Father then mother for stable path ordering.
        for parent_xref, sex in ((fam.husband, "F"), (fam.wife, "M")):
            if not parent_xref or parent_xref in paths:
                continue
            paths[parent_xref] = paths[x] + [sex]
            queue.append(parent_xref)
    return paths


def _collect_aunts_uncles(
    ancestor_paths: dict[str, list[str]],
    indis: dict[str, Individual],
    fams: dict[str, Family],
) -> list[tuple[str, str]]:
    """For each ancestor at gen >= 1 (a parent or grandparent etc.), look at
    their FAMC (the family they were a child in) and label their siblings.

    Returns a list of (xref, relationship_label) for aunts/uncles.
    Path-based, no names used.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    # Group ancestors by their line + depth to give aunts a stable index.
    # We need this in a deterministic order, so sort by path tuple.
    sorted_ancestors = sorted(
        (
            (path, xref)
            for xref, path in ancestor_paths.items()
            if len(path) >= 1
        ),
        key=lambda pair: (len(pair[0]), pair[0]),
    )

    # For each ancestor, find their *parents'* family and walk siblings.
    counter_by_line: dict[str, int] = {}
    for path, ancestor_xref in sorted_ancestors:
        ancestor = indis.get(ancestor_xref)
        if not ancestor or not ancestor.famc:
            continue
        fam = fams.get(ancestor.famc)
        if not fam:
            continue
        line = "paternal" if path[0] == "F" else "maternal"
        for sib_xref in fam.children:
            if sib_xref == ancestor_xref:
                continue
            if sib_xref in ancestor_paths:
                # already labeled as a (more direct) ancestor
                continue
            if sib_xref in seen:
                continue
            seen.add(sib_xref)
            sib = indis.get(sib_xref)
            if not sib:
                continue
            kind = "uncle" if sib.sex == "M" else "aunt"
            # Depth-aware label: gen 2 ancestor -> sibling is aunt/uncle,
            # gen 3 -> great-aunt/uncle, etc.
            depth = len(path)
            if depth == 1:
                # ancestor IS root's parent; sibling is root's aunt/uncle
                base = f"{line}_{kind}"
            elif depth == 2:
                base = f"{line}_great{kind}"
            else:
                base = f"{line}_great{depth - 1}_{kind}"
            counter_by_line[base] = counter_by_line.get(base, 0) + 1
            label = f"{base}_{counter_by_line[base]}"
            out.append((sib_xref, label))
    return out


def parse_gedcom_to_pedigree(
    gedcom_path: Path, source_tag: str
) -> list[PedigreeRow]:
    """Read GEDCOM, return name-free pedigree rows for root + direct
    ancestors + their siblings (aunts/uncles, great-aunts/uncles, ...)."""
    indis, fams = parse_gedcom(gedcom_path)
    if ROOT_INDI not in indis:
        # Fallback: pick the youngest male as root (best heuristic if the
        # canonical xref changes). But for THIS repo the constant is right.
        raise RuntimeError(f"Root individual {ROOT_INDI} not found in GEDCOM")

    ancestor_paths = _walk_ancestors(ROOT_INDI, indis, fams)
    aunts_uncles = _collect_aunts_uncles(ancestor_paths, indis, fams)

    rows: list[PedigreeRow] = []

    for xref, path in ancestor_paths.items():
        indi = indis.get(xref)
        if not indi:
            continue
        rel = _ancestor_label(path)
        rows.append(
            PedigreeRow(
                person_id=_person_id_for(xref, source_tag),
                relationship=rel,
                sex=indi.sex or "",
                birth_year=indi.birth_year,
                death_year=indi.death_year,
                source=source_tag,
            )
        )

    for xref, rel in aunts_uncles:
        indi = indis.get(xref)
        if not indi:
            continue
        rows.append(
            PedigreeRow(
                person_id=_person_id_for(xref, source_tag),
                relationship=rel,
                sex=indi.sex or "",
                birth_year=indi.birth_year,
                death_year=indi.death_year,
                source=source_tag,
            )
        )

    return rows
