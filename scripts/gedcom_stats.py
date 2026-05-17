"""
GEDCOM analysis: tree depth, geographic concentration, surname distribution,
deduplicated ancestor list, and era-adjusted longevity.

Usage:
    python scripts/gedcom_stats.py [path-to-ged]

No external dependencies.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_GED = Path("w_data/craig_gedcom/Craig Family Tree.ged")
ROOT_INDI = "@I292246897494@"  # William Craig, b. 1995

# Below this birth year, Ancestry tree dates routinely contain errors
# (one parent's age confused for another, century-off transcriptions, etc.).
RELIABLE_BIRTH_YEAR = 1700

# Rough "top-decile adult-survivor age at death" by birth era. Approximations
# from historical demography (Wrigley/Schofield for England; Italian regional
# data; HMD for 20th-century onward). Used only as a sanity threshold for
# "exceptional longevity" -- not a precise percentile.
ERA_LONGEVITY_THRESHOLD = [
    (1600, 80),
    (1700, 82),
    (1800, 84),
    (1900, 87),
    (1950, 90),
    (2000, 92),
]

GED_DATE_RE = re.compile(
    r"(?:(\d{1,2})\s+)?(?:(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+)?(\d{3,4})",
    re.IGNORECASE,
)


@dataclass
class Individual:
    xref: str
    name: str = ""
    surname: str = ""
    given: str = ""
    sex: str = ""
    birth_year: int | None = None
    birth_place: str = ""
    death_year: int | None = None
    death_place: str = ""
    death_cause: str = ""
    famc: str = ""
    fams: list[str] = field(default_factory=list)


@dataclass
class Family:
    xref: str
    husband: str = ""
    wife: str = ""
    children: list[str] = field(default_factory=list)


def parse_year(value: str) -> int | None:
    m = GED_DATE_RE.search(value or "")
    if not m:
        return None
    year = int(m.group(3))
    return year if 1000 <= year <= 2100 else None


def parse_gedcom(path: Path) -> tuple[dict[str, Individual], dict[str, Family]]:
    indis: dict[str, Individual] = {}
    fams: dict[str, Family] = {}
    cur_indi: Individual | None = None
    cur_fam: Family | None = None
    cur_event: str | None = None

    with path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\r\n")
            if not line:
                continue
            parts = line.split(" ", 2)
            try:
                level = int(parts[0])
            except ValueError:
                continue

            if level == 0:
                cur_indi = None
                cur_fam = None
                cur_event = None
                if len(parts) >= 3 and parts[2] == "INDI":
                    cur_indi = Individual(xref=parts[1])
                    indis[parts[1]] = cur_indi
                elif len(parts) >= 3 and parts[2] == "FAM":
                    cur_fam = Family(xref=parts[1])
                    fams[parts[1]] = cur_fam
                continue

            tag = parts[1] if len(parts) >= 2 else ""
            value = parts[2] if len(parts) >= 3 else ""

            if cur_indi is not None:
                if level == 1:
                    cur_event = None
                    if tag == "NAME":
                        cur_indi.name = value
                        m = re.search(r"/([^/]+)/", value)
                        if m:
                            cur_indi.surname = m.group(1)
                            cur_indi.given = value[: m.start()].strip()
                    elif tag == "SEX":
                        cur_indi.sex = value
                    elif tag == "BIRT":
                        cur_event = "BIRT"
                    elif tag == "DEAT":
                        cur_event = "DEAT"
                    elif tag == "FAMC":
                        cur_indi.famc = value
                    elif tag == "FAMS":
                        cur_indi.fams.append(value)
                elif level == 2 and cur_event:
                    if tag == "DATE":
                        year = parse_year(value)
                        if cur_event == "BIRT":
                            cur_indi.birth_year = year
                        else:
                            cur_indi.death_year = year
                    elif tag == "PLAC":
                        if cur_event == "BIRT":
                            cur_indi.birth_place = value
                        else:
                            cur_indi.death_place = value
                    elif tag == "CAUS" and cur_event == "DEAT":
                        cur_indi.death_cause = value

            if cur_fam is not None and level == 1:
                if tag == "HUSB":
                    cur_fam.husband = value
                elif tag == "WIFE":
                    cur_fam.wife = value
                elif tag == "CHIL":
                    cur_fam.children.append(value)

    return indis, fams


def collect_ancestors(
    root: str, indis: dict[str, Individual], fams: dict[str, Family]
) -> dict[str, int]:
    seen: dict[str, int] = {root: 0}
    stack = [(root, 0)]
    while stack:
        xref, gen = stack.pop()
        indi = indis.get(xref)
        if not indi or not indi.famc:
            continue
        fam = fams.get(indi.famc)
        if not fam:
            continue
        for parent in (fam.husband, fam.wife):
            if parent and parent not in seen:
                seen[parent] = gen + 1
                stack.append((parent, gen + 1))
    return seen


def identity_key(indi: Individual) -> tuple[str, str, int]:
    """A loose identity key for deduping duplicate INDI records that refer to
    the same real person. Normalizes given+surname and uses birth year."""
    given = re.sub(r"[^a-z]", "", indi.given.lower())[:8]
    surn = re.sub(r"[^a-z]", "", indi.surname.lower())
    return (given, surn, indi.birth_year or 0)


def dedupe_ancestors(
    ancestor_xrefs: list[str], indis: dict[str, Individual]
) -> list[Individual]:
    """Collapse duplicate INDI records into a single canonical individual,
    preferring the record with the most data."""
    by_key: dict[tuple, Individual] = {}
    for x in ancestor_xrefs:
        i = indis.get(x)
        if not i or not i.surname:
            if i:
                by_key.setdefault((x, "", 0), i)
            continue
        k = identity_key(i)
        existing = by_key.get(k)
        if existing is None:
            by_key[k] = i
            continue

        def score(p: Individual) -> int:
            return (
                (1 if p.birth_year else 0)
                + (1 if p.death_year else 0)
                + (1 if p.birth_place else 0)
                + len(p.name) // 10
            )

        if score(i) > score(existing):
            by_key[k] = i
    return list(by_key.values())


def era_threshold(birth_year: int) -> int:
    threshold = ERA_LONGEVITY_THRESHOLD[0][1]
    for year, t in ERA_LONGEVITY_THRESHOLD:
        if birth_year >= year:
            threshold = t
    return threshold


def country_of(place: str) -> str:
    if not place:
        return "(unknown)"
    last = place.split(",")[-1].strip()
    return last or "(unknown)"


def safe(s: str) -> str:
    return s.encode("ascii", "replace").decode("ascii")


def main() -> None:
    ged_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_GED
    indis, fams = parse_gedcom(ged_path)

    print(f"=== {ged_path.name} ===")
    print(f"Individuals: {len(indis):,}   Families: {len(fams):,}")

    cause_count = sum(1 for i in indis.values() if i.death_cause)
    print(f"Individuals with recorded cause of death: {cause_count}")

    root_indi = indis.get(ROOT_INDI)
    if not root_indi:
        print(f"Root individual {ROOT_INDI} not found.")
        return

    print(f"\n--- Direct ancestors of {safe(root_indi.name)} ---")
    ancestor_map = collect_ancestors(ROOT_INDI, indis, fams)
    raw_xrefs = list(ancestor_map.keys())
    deduped = dedupe_ancestors(raw_xrefs, indis)
    print(f"Raw direct ancestors:     {len(raw_xrefs) - 1}")
    print(f"After dedup: {len(deduped) - 1}")

    gen_counts: Counter[int] = Counter()
    for g in ancestor_map.values():
        gen_counts[g] += 1
    print("\nGeneration breakdown (expected = 2^g):")
    for g in sorted(gen_counts):
        expected = 2**g if g > 0 else 1
        print(f"  gen {g:2d}: {gen_counts[g]:4d} / {expected}")

    countries: Counter[str] = Counter()
    full_places: Counter[str] = Counter()
    surnames: Counter[str] = Counter()
    earliest: int | None = None
    for i in deduped:
        if i.surname:
            surnames[i.surname] += 1
        if i.birth_place:
            countries[country_of(i.birth_place)] += 1
            full_places[i.birth_place] += 1
        if i.birth_year and (earliest is None or i.birth_year < earliest):
            earliest = i.birth_year

    print(f"\nEarliest direct-ancestor birth year: {earliest}")

    print("\nTop ancestral surnames (deduped):")
    for n, c in surnames.most_common(15):
        print(f"  {c:3d}  {n}")
    print("\nTop ancestral birth countries:")
    for n, c in countries.most_common(10):
        print(f"  {c:3d}  {n}")
    print("\nTop ancestral birth places (full):")
    for n, c in full_places.most_common(15):
        print(f"  {c:3d}  {n}")

    aged: list[tuple[int, int, str, str, int, str]] = []
    for i in deduped:
        if not (i.birth_year and i.death_year):
            continue
        age = i.death_year - i.birth_year
        if not (0 < age < 120):
            continue
        if i.birth_year < RELIABLE_BIRTH_YEAR:
            continue
        thr = era_threshold(i.birth_year)
        aged.append((age, thr, i.name, i.birth_place, i.birth_year, i.surname))

    print(f"\n--- Direct-ancestor longevity (deduped, reliable post-{RELIABLE_BIRTH_YEAR}, n={len(aged)}) ---")
    for thresh in (80, 85, 90, 95, 100):
        c = sum(1 for age, *_ in aged if age >= thresh)
        print(f"  >={thresh}:  {c}")

    superstars = sorted(
        ((age, thr, name, place, by, sur) for age, thr, name, place, by, sur in aged if age >= thr),
        key=lambda t: (t[0] - t[1]),
        reverse=True,
    )
    print(f"\nEra-adjusted longevity superstars, n={len(superstars)}:")
    print(f"  {'age':>3}  {'+era':>4}  {'born':>4}  {'surname':<14}  {'name':<32}  {'place'}")
    for age, thr, name, place, by, sur in superstars[:40]:
        plus = age - thr
        place_short = place.split(",")[0][:35] if place else ""
        sur_s = safe(sur)[:14]
        name_s = safe(name)[:32]
        print(f"  {age:3d}  {plus:+4d}  {by:4d}  {sur_s:<14}  {name_s:<32}  {place_short}")

    print("\nSuperstars grouped by ancestral cluster:")
    cluster_buckets: dict[str, list[tuple[int, int, str, int]]] = defaultdict(list)
    for age, thr, name, place, by, _ in superstars:
        p = place.lower()
        if "campolieto" in p or "campobasso" in p or "molise" in p:
            bucket = "Italy: Molise (Campolieto cluster)"
        elif "salerno" in p or "campania" in p or "bellosguardo" in p:
            bucket = "Italy: Campania/Salerno"
        elif "italy" in p or "italia" in p:
            bucket = "Italy: other"
        elif "devon" in p or "shebbear" in p or "parkham" in p:
            bucket = "England: Devon"
        elif "kent" in p:
            bucket = "England: Kent"
        elif "dorset" in p or "gillingham" in p:
            bucket = "England: Dorset"
        elif "england" in p or "united kingdom" in p:
            bucket = "England: other"
        elif "massachusetts" in p or "connecticut" in p or "rhode island" in p:
            bucket = "Colonial New England"
        elif "pennsylvania" in p or "pittsburgh" in p:
            bucket = "PA (Italian-American)"
        elif "posen" in p or "poland" in p:
            bucket = "Poland (Posen)"
        elif "germany" in p:
            bucket = "Germany"
        elif "netherlands" in p:
            bucket = "Netherlands"
        else:
            bucket = "(unclassified)"
        cluster_buckets[bucket].append((age, age - thr, name, by))
    for bucket, members in sorted(cluster_buckets.items(), key=lambda x: -len(x[1])):
        ages_here = [a for a, *_ in members]
        avg = sum(ages_here) / len(ages_here)
        print(f"\n  {bucket}: n={len(members)}, mean age={avg:.1f}")
        for age, plus, name, by in sorted(members, reverse=True):
            print(f"    {age:3d}y ({plus:+d} vs era)  b.{by}  {safe(name)}")


if __name__ == "__main__":
    main()
