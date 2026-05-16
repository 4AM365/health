"""
Cross-references direct ancestors' lifespans against WikiTree's public API.

For each ancestor with a GEDCOM-claimed birth and death year (post-1700), this
issues a name+birth-year search against WikiTree, then compares the returned
death year. Each ancestor is tagged with a confidence label:

  CONFIRMED       WikiTree death year within +/-1 of GEDCOM
  MINOR_DIFF      WikiTree death year within +/-5 of GEDCOM (probably same person)
  CONTRADICTED    WikiTree shows a markedly different death year (>5 yr diff)
  AMBIGUOUS       Multiple WikiTree candidates, no clean match
  NOT_FOUND       No WikiTree match for this person
  ERROR           Network/API problem (transient)

Why this matters: Ancestry tree imports routinely contain conflated records
that produce phantom centenarians. A cross-source check separates verified
longevity signal from data-quality noise.

Usage:
    python scripts/verify_ancestors.py [path-to-ged]

No third-party dependencies; uses stdlib urllib.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Import shared GEDCOM parsing from sibling script
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gedcom_stats import (  # type: ignore
    DEFAULT_GED,
    RELIABLE_BIRTH_YEAR,
    ROOT_INDI,
    collect_ancestors,
    dedupe_ancestors,
    identity_key,
    parse_gedcom,
    safe,
)

API_URL = "https://api.wikitree.com/api.php"
USER_AGENT = "ancestral-diet-verifier/0.1 (personal genealogy research)"
RATE_LIMIT_SECONDS = 1.6  # polite spacing between API calls
MAX_RETRIES_ON_429 = 4
BACKOFF_START_SECONDS = 30  # doubles each retry: 30, 60, 120, 240


def first_given(given: str) -> str:
    """WikiTree searches respond best to a single given name."""
    if not given:
        return ""
    # Strip parentheticals like "(Deacon)" and titles
    cleaned = re.sub(r"\([^)]*\)", "", given)
    cleaned = re.sub(r'"[^"]*"', "", cleaned)
    tokens = cleaned.split()
    return tokens[0] if tokens else ""


def wikitree_search(first: str, last: str, birth_year: int) -> tuple[str, list[dict]]:
    """Returns (raw_status_str, matches). matches is a list of WikiTree person dicts.
    Retries on HTTP 429 with exponential backoff."""
    params = {
        "action": "searchPerson",
        "FirstName": first,
        "LastName": last,
        "BirthDate": str(birth_year),
        "BirthDateSpread": "2",
        "fields": "Name,FirstName,LastNameAtBirth,LastNameCurrent,BirthDate,DeathDate,BirthLocation,DeathLocation",
        "format": "json",
        "limit": "10",
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    backoff = BACKOFF_START_SECONDS
    for attempt in range(MAX_RETRIES_ON_429 + 1):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < MAX_RETRIES_ON_429:
                print(f"    [429, sleeping {backoff}s and retrying...]", flush=True)
                time.sleep(backoff)
                backoff *= 2
                continue
            raise
    else:
        raise RuntimeError("Exhausted retries on 429")

    data = json.loads(body)
    if not isinstance(data, list) or not data:
        return ("empty-envelope", [])
    env = data[0]
    matches = env.get("matches") or []
    status = str(env.get("status", "0"))
    return (status, matches)


def year_from_date(date_str: str | None) -> int | None:
    if not date_str:
        return None
    m = re.match(r"(\d{4})", date_str)
    if not m:
        return None
    y = int(m.group(1))
    return y if 1000 <= y <= 2100 else None


def classify(
    gedcom_birth: int,
    gedcom_death: int,
    matches: list[dict],
    expected_surname: str,
) -> tuple[str, dict | None, str]:
    """Returns (label, best_match_or_none, note)."""
    if not matches:
        return ("NOT_FOUND", None, "no WikiTree candidates")

    # Filter: must have a death year and surname match (loose)
    target_sur = re.sub(r"[^a-z]", "", expected_surname.lower())
    plausible = []
    for m in matches:
        sur = (m.get("LastNameAtBirth") or m.get("LastNameCurrent") or "")
        sur_norm = re.sub(r"[^a-z]", "", sur.lower())
        if target_sur and target_sur != sur_norm:
            continue
        wt_birth = year_from_date(m.get("BirthDate"))
        if wt_birth is None or abs(wt_birth - gedcom_birth) > 3:
            continue
        plausible.append(m)

    if not plausible:
        return ("NOT_FOUND", None, f"{len(matches)} returned but none with matching surname/birth-year")

    if len(plausible) > 1:
        # Prefer ones with a death year for the comparison
        with_death = [m for m in plausible if year_from_date(m.get("DeathDate"))]
        if len(with_death) == 1:
            plausible = with_death
        else:
            return ("AMBIGUOUS", plausible[0], f"{len(plausible)} candidates match birth+surname")

    best = plausible[0]
    wt_death = year_from_date(best.get("DeathDate"))
    if wt_death is None:
        return ("AMBIGUOUS", best, "match found but no WikiTree death year recorded")

    diff = wt_death - gedcom_death
    if abs(diff) <= 1:
        return ("CONFIRMED", best, f"WikiTree death {wt_death} matches GEDCOM {gedcom_death}")
    if abs(diff) <= 5:
        return ("MINOR_DIFF", best, f"WikiTree death {wt_death} vs GEDCOM {gedcom_death} (diff {diff:+d})")
    return (
        "CONTRADICTED",
        best,
        f"WikiTree death {wt_death} vs GEDCOM {gedcom_death} (diff {diff:+d}) -- likely wrong-person merge",
    )


def main() -> None:
    ged_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_GED
    indis, fams = parse_gedcom(ged_path)
    ancestor_map = collect_ancestors(ROOT_INDI, indis, fams)
    deduped = dedupe_ancestors(list(ancestor_map.keys()), indis)

    # Only verify ancestors with both dates and post-RELIABLE_BIRTH_YEAR births,
    # since pre-1700 GEDCOM dates are dubious AND WikiTree coverage thins.
    targets = []
    for i in deduped:
        if not (i.birth_year and i.death_year):
            continue
        age = i.death_year - i.birth_year
        if not (0 < age < 120):
            continue
        if i.birth_year < RELIABLE_BIRTH_YEAR:
            continue
        if not i.surname:
            continue
        targets.append(i)

    # Sort: longest-claimed-life first, since those are the highest-priority
    # claims to verify (also exactly where Ancestry errors concentrate)
    targets.sort(key=lambda p: -(p.death_year - p.birth_year))

    print(f"Verifying {len(targets)} direct ancestors against WikiTree...\n")
    print(f"{'label':<13}  {'age':>3}  {'born':>4}  {'died':>4}  {'surname':<14}  name")
    print("-" * 110)

    summary: dict[str, int] = {}
    details: list[dict] = []

    for i, p in enumerate(targets, 1):
        first = first_given(p.given)
        sur = p.surname
        gedcom_age = p.death_year - p.birth_year

        try:
            time.sleep(RATE_LIMIT_SECONDS)
            status, matches = wikitree_search(first, sur, p.birth_year)
            label, best, note = classify(p.birth_year, p.death_year, matches, sur)
        except Exception as e:
            label, best, note = ("ERROR", None, f"{type(e).__name__}: {e}")

        summary[label] = summary.get(label, 0) + 1
        details.append(
            {
                "name": p.name,
                "surname": p.surname,
                "birth_year": p.birth_year,
                "death_year": p.death_year,
                "gedcom_age": gedcom_age,
                "birth_place": p.birth_place,
                "label": label,
                "note": note,
                "wikitree_id": best.get("Name") if best else None,
                "wikitree_birth": best.get("BirthDate") if best else None,
                "wikitree_death": best.get("DeathDate") if best else None,
            }
        )
        print(
            f"  {label:<11}  {gedcom_age:3d}  {p.birth_year:4d}  {p.death_year:4d}  "
            f"{safe(sur):<14}  {safe(p.name)[:50]}  // {note[:60]}"
        )

    print("\n--- Verification summary ---")
    for label in ("CONFIRMED", "MINOR_DIFF", "CONTRADICTED", "AMBIGUOUS", "NOT_FOUND", "ERROR"):
        n = summary.get(label, 0)
        if n:
            print(f"  {label:<13}: {n}")

    # Highlight the changes that affect the longevity superstars list
    print("\n--- Longevity claims at risk (CONTRADICTED only) ---")
    contradicted = [d for d in details if d["label"] == "CONTRADICTED"]
    if not contradicted:
        print("  None — every disputed lifespan was either confirmed or minor.")
    for d in contradicted:
        print(f"  {d['gedcom_age']}y claimed for {safe(d['name'])} b.{d['birth_year']}")
        print(f"      GEDCOM death: {d['death_year']}   WikiTree death: {d['wikitree_death']}")
        print(f"      WikiTree ID:  {d['wikitree_id']}")

    # Dump JSON for downstream consumption (gitignored data path implied;
    # we just write to stdout, caller can redirect)
    json_out = Path("verification_report.json")
    json_out.write_text(json.dumps(details, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nFull verification report written to: {json_out.resolve()}")


if __name__ == "__main__":
    main()
