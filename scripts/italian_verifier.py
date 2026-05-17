"""
Generate a manual-review checklist for Italian-born ancestors.

WikiTree coverage of Italian ancestors is sparse. The right sources are:
- Antenati (Italian state archive digital portal) for civil registration
  records, ~1809+ in southern Italy. Anti-scraping; emits URLs for manual review.
- Diocesan archives for pre-1809 records. Mostly NOT online; require in-person
  or paid-genealogist consultation.

Categories:
  ONLINE_VERIFIABLE   civil-registry era (>=1809), Antenati / FamilySearch URLs
  PARISH_REQUIRED     pre-1809, needs diocesan archive
  (CONFIRMED via independent sources noted inline for select ancestors)

Usage:
    python scripts/italian_verifier.py [path-to-ged]
"""

from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gedcom_stats import (  # type: ignore
    DEFAULT_GED,
    ROOT_INDI,
    collect_ancestors,
    dedupe_ancestors,
    parse_gedcom,
    safe,
)

CIVIL_REGISTRY_START_YEAR = 1809  # Southern Italy: Napoleonic civil reform

# More specific entries first (first match wins).
# Sant'Elia a Pianisi was under Archdiocese of Benevento until 1983
# (transferred to Campobasso-Boiano by John Paul II in 1983).
PLACE_TO_PARISH_ARCHIVE = [
    ("sant'elia a pianisi", "Archivio Diocesano di Benevento (pre-1983 jurisdiction; transferred to Campobasso-Boiano in 1983)"),
    ("sant elia a pianisi", "Archivio Diocesano di Benevento (pre-1983 jurisdiction)"),
    ("bellosguardo", "Archivio Diocesano di Vallo della Lucania (Salerno province)"),
    ("serracapriola", "Archivio Diocesano di Termoli-Larino"),
    ("campolieto", "Archivio Diocesano di Campobasso-Boiano (historically Diocese of Boiano)"),
    ("campodipietra", "Archivio Diocesano di Campobasso-Boiano"),
    ("salerno", "Archivio Diocesano di Salerno"),
    ("campobasso", "Archivio Diocesano di Campobasso-Boiano"),
]

# Independently confirmed via prior web searches (census, cemetery, multiple sources).
ALREADY_CONFIRMED = {
    ("ialenti", 1858, 1939): "Multi-source confirmed: PA census 1900/1910/1920/1930, "
                              "Mt. Carmel Cemetery Pittsburgh, multiple genealogy sites agree "
                              "on Feb 22 1858 - Jan 4 1939 (GEDCOM has Feb 21 / Jan 2).",
}


def antenati_search_url(name: str) -> str:
    q = name.strip()
    return f"https://antenati.cultura.gov.it/?s={urllib.parse.quote(q)}"


def familysearch_search_url(first: str, last: str, place: str, year: int | None) -> str:
    parts = []
    if first:
        parts.append(f"q.givenName={urllib.parse.quote(first)}")
    if last:
        parts.append(f"q.surname={urllib.parse.quote(last)}")
    if place:
        parts.append(f"q.birthLikePlace={urllib.parse.quote(place)}")
    if year:
        parts.append(f"q.birthLikeDate.from={year - 2}")
        parts.append(f"q.birthLikeDate.to={year + 2}")
    return "https://www.familysearch.org/search/record/results?" + "&".join(parts)


def parish_archive_for(place: str) -> str | None:
    p = place.lower()
    for key, archive in PLACE_TO_PARISH_ARCHIVE:
        if key in p:
            return archive
    return None


def is_italian_place(place: str) -> bool:
    p = place.lower()
    return any(
        k in p for k in ("italy", "italia", "molise", "campobasso", "campolieto",
                         "campodipietra", "salerno", "campania", "bellosguardo",
                         "sant'elia", "sant elia")
    )


def classify(birth: int | None, death: int | None) -> str:
    if (birth and birth >= CIVIL_REGISTRY_START_YEAR) or (
        death and death >= CIVIL_REGISTRY_START_YEAR
    ):
        return "ONLINE_VERIFIABLE"
    return "PARISH_REQUIRED"


def main() -> None:
    ged_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_GED
    indis, fams = parse_gedcom(ged_path)
    ancestor_map = collect_ancestors(ROOT_INDI, indis, fams)
    deduped = dedupe_ancestors(list(ancestor_map.keys()), indis)

    italian = [
        i for i in deduped
        if i.birth_place and is_italian_place(i.birth_place)
    ]
    italian_amer = [
        i for i in deduped
        if i.surname.lower() in ("yalenty", "ialenti")
        and i.birth_place
        and not is_italian_place(i.birth_place)
    ]

    print("# Italian ancestor verification checklist\n")
    print(f"Italian-born direct ancestors: {len(italian)}")
    print(f"Italian-American (Ialenti/Yalenty, US-born): {len(italian_amer)}\n")

    summary: dict[str, int] = {}

    def emit(i, label: str):
        nonlocal summary
        summary[label] = summary.get(label, 0) + 1
        by = i.birth_year or "?"
        dy = i.death_year or "?"
        age = ""
        if i.birth_year and i.death_year:
            age = f" (age {i.death_year - i.birth_year})"
        print(f"### [{label}] {safe(i.name)}")
        print(f"- **GEDCOM**: b.{by} d.{dy}{age}, {i.birth_place}")
        key = (i.surname.lower(), i.birth_year, i.death_year)
        if key in ALREADY_CONFIRMED:
            print(f"- **Status**: {ALREADY_CONFIRMED[key]}")
            return
        if label == "PARISH_REQUIRED":
            archive = parish_archive_for(i.birth_place) or "(unknown diocese for this place)"
            print(f"- **Source needed**: {archive}")
            print(f"- **Records sought**: baptism (battesimo) and death (morto) registers, "
                  f"~{i.birth_year}-{i.death_year}")
            print(f"- **How**: in-person or via paid Italian genealogist; not online")
        elif label == "ONLINE_VERIFIABLE":
            first = i.given.split()[0] if i.given else ""
            italian_birth = i.birth_place and is_italian_place(i.birth_place)
            italian_death = i.death_place and is_italian_place(i.death_place)

            print(f"- **FamilySearch**: "
                  f"{familysearch_search_url(first, i.surname, i.birth_place or '', i.birth_year)}")

            if italian_birth or italian_death:
                print(f"- **Antenati search**: {antenati_search_url(i.name.replace('/', ''))}")

            if italian_birth and i.birth_year and i.birth_year >= CIVIL_REGISTRY_START_YEAR:
                comune = i.birth_place.split(",")[0].strip()
                print(f"- **Antenati browse**: Archivio di Stato di Campobasso > "
                      f"Stato civile italiano > {comune} > Nati {i.birth_year}")
            if italian_death and i.death_year and i.death_year >= CIVIL_REGISTRY_START_YEAR:
                comune = i.death_place.split(",")[0].strip()
                print(f"- **Antenati browse**: Archivio di Stato di Campobasso > "
                      f"Stato civile italiano > {comune} > Morti {i.death_year}")

            if (i.birth_place and not italian_birth) or (i.death_place and not italian_death):
                print(f"- **US sources** (immigrant generation): SSDI, US Census 1900-1950, "
                      f"naturalization records (NARA), Find A Grave, local newspaper obit archives")
        print()

    print("\n## Italian-born ancestors\n")
    for i in sorted(italian, key=lambda x: (x.birth_year or 0)):
        label = classify(i.birth_year, i.death_year)
        emit(i, label)

    if italian_amer:
        print("\n## Italian-American (post-immigration)\n")
        for i in sorted(italian_amer, key=lambda x: (x.birth_year or 0)):
            emit(i, "ONLINE_VERIFIABLE")

    print("\n## Summary\n")
    for label in ("ONLINE_VERIFIABLE", "PARISH_REQUIRED"):
        n = summary.get(label, 0)
        if n:
            print(f"- {label}: {n}")

    print("\n## Notes")
    print("- Antenati blocks programmatic access -- manual browsing only.")
    print("- For pre-1809 ancestors (Colavita 1704, Mancini 1704), the right "
          "next step is contacting the relevant diocesan archive directly, "
          "or commissioning a Molise-based genealogist "
          "(typical cost: EUR 200-400 for a focused parish lookup).")


if __name__ == "__main__":
    main()
