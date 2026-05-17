"""Parse the DEXA body composition PDF into body_comp rows.

The DEXA report PDF has scrubbed personal fields (dates, name, etc. appear as
"####"), but the **filename** carries the measurement date in M-D-YY form (e.g.
`William Craig 3-3-22 Dexa ...`). We pull the date from the filename and the
numeric body-comp values from page 1 text.

Schema target: body_comp(date PK, bf_pct, lbm_kg, fat_mass_kg, vat_g, bmd,
source_file). The DEXA report we have does NOT print a raw BMD g/cm^2 value;
it prints only the T-score (0.8) and Z-score (0.4). We store the T-score in
`bmd` (more actionable than raw density for the dashboard; documented here so
the dashboard agent knows what the column actually holds for DEXA rows).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pdfplumber

LB_TO_KG = 0.453592
LB_TO_G = 453.592


def _date_from_filename(path: Path) -> date | None:
    """Pull a date from filenames like 'William Craig 3-3-22 Dexa ...'."""
    m = re.search(r"(\d{1,2})-(\d{1,2})-(\d{2,4})", path.name)
    if not m:
        return None
    mm, dd, yy = (int(x) for x in m.groups())
    if yy < 100:
        yy += 2000
    try:
        return date(yy, mm, dd)
    except ValueError:
        return None


def _extract_numbers(text: str) -> dict[str, float]:
    """Pull body-comp fields from the page-1 summary text.

    Page 1 contains a line shaped like:
        "#### 195.7 lbs - 143.0 lbs - 46.3 lbs - 24.5% -"
    in the order: weight, lean tissue, fat tissue, body-fat %.
    Page 2 has visceral fat pounds.
    Page 6 has BMD T-Score.
    """
    out: dict[str, float] = {}

    # Summary row: weight, lean, fat, bf%
    m = re.search(
        r"####\s+([\d.]+)\s*lbs\s*-\s*([\d.]+)\s*lbs\s*-\s*([\d.]+)\s*lbs\s*-\s*([\d.]+)\s*%",
        text,
    )
    if m:
        _wt_lb, lean_lb, fat_lb, bf_pct = (float(x) for x in m.groups())
        out["bf_pct"] = bf_pct
        out["lbm_kg"] = round(lean_lb * LB_TO_KG, 3)
        out["fat_mass_kg"] = round(fat_lb * LB_TO_KG, 3)

    # Visceral fat pounds — appears on page 2 as e.g. "#### 0.97 - 1.34"
    m = re.search(r"####\s+([\d.]+)\s*-\s*[\d.]+\s*(?:\n|$)", text)
    if m:
        vat_lb = float(m.group(1))
        # Only adopt if it's plausibly visceral (typically <3 lb) — avoids
        # collision with the summary line that starts the same way.
        if vat_lb < 5:
            out["vat_g"] = round(vat_lb * LB_TO_G, 1)

    # BMD T-Score line on page 6: "T-Score: 0.8"
    m = re.search(r"T-Score:\s*(-?[\d.]+)", text)
    if m:
        out["bmd"] = float(m.group(1))

    return out


def parse_dexa(pdf_path: Path) -> list[dict]:
    """Return a list of body_comp row dicts (typically 0 or 1)."""
    measured = _date_from_filename(pdf_path)
    if measured is None:
        print(f"[body] dexa: SKIP {pdf_path.name} — no date in filename")
        return []

    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)

    nums = _extract_numbers(text)
    if "bf_pct" not in nums:
        print(f"[body] dexa: SKIP {pdf_path.name} — no body-fat summary row found")
        return []

    row = {
        "date": measured.isoformat(),
        "bf_pct": nums.get("bf_pct"),
        "lbm_kg": nums.get("lbm_kg"),
        "fat_mass_kg": nums.get("fat_mass_kg"),
        "vat_g": nums.get("vat_g"),
        "bmd": nums.get("bmd"),
        "source_file": pdf_path.name,
    }
    return [row]
