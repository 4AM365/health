"""Pull body-comp rows out of Will's catch-all `Health.xlsx`.

The workbook is shared across domains. We touch only sheets that are
unambiguously body-shaped:

  - **Bloodwork** sheet's *first three rows* are body-comp (Bodyweight, DEXA
    fat %, DEXA Visceral) with one column per measurement date. Everything
    from row 8 onward is lipid-panel/CBC stuff owned by the bloodwork agent
    — we leave it alone.
  - **Physical Stats**, **FatOxRate**, **To-Do**, **Workout Volume** sheets
    are either nutrition-owned, dateless, or off-domain. Logged as skipped.

No sleep data lives in this workbook today, so the function only emits
`body_comp` rows.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

LB_TO_KG = 0.453592
LB_TO_G = 453.592

BODY_SHEET = "Bloodwork"
SKIP_SHEETS = {"Physical Stats", "FatOxRate", "To-Do", "Workout Volume"}


def _as_date(x) -> date | None:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return None


def _as_float(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if pd.isna(v):
        return None
    return v


def parse_health_xlsx(xlsx_path: Path) -> list[dict]:
    xl = pd.ExcelFile(xlsx_path)

    for name in xl.sheet_names:
        if name in SKIP_SHEETS:
            print(
                f"[body] health_xlsx: SKIP sheet {name!r} — "
                "off-domain (nutrition / dateless / non-body)"
            )

    if BODY_SHEET not in xl.sheet_names:
        print(f"[body] health_xlsx: SKIP — no {BODY_SHEET!r} sheet present")
        return []

    df = pd.read_excel(xlsx_path, sheet_name=BODY_SHEET, header=None)
    # Row 0 holds the per-measurement dates in cols 2..6 (col 0/1 are labels).
    header_row = df.iloc[0]
    date_cols: dict[int, date] = {}
    for c in range(len(header_row)):
        d = _as_date(header_row[c])
        if d is not None:
            date_cols[c] = d

    if not date_cols:
        print(f"[body] health_xlsx: SKIP {BODY_SHEET!r} — no date headers in row 0")
        return []

    # Per measurement date, gather the body-comp fields we know how to map.
    by_date: dict[date, dict] = {d: {} for d in date_cols.values()}
    for _, row in df.iloc[1:].iterrows():
        label = row[0]
        if not isinstance(label, str):
            continue
        key = label.strip().lower()
        # We only care about the three body rows at the top of the sheet.
        if key not in {"bodyweight", "dexa fat %", "dexa visceral"}:
            continue
        for col, d in date_cols.items():
            val = _as_float(row[col])
            if val is None:
                continue
            slot = by_date[d]
            if key == "bodyweight":
                # Sheet stores pounds. Will doesn't actually need a body-weight
                # column today (schema only has lbm/fat), but it lets us derive
                # fat_mass_kg when paired with DEXA fat %.
                slot["_bw_kg"] = round(val * LB_TO_KG, 3)
            elif key == "dexa fat %":
                slot["bf_pct"] = val
            elif key == "dexa visceral":
                # Sheet rows show 1.0 / 0.5 which match the DEXA report's
                # "Visceral Fat Pounds" units. Convert to grams.
                slot["vat_g"] = round(val * LB_TO_G, 1)

    rows: list[dict] = []
    for d, slot in sorted(by_date.items()):
        if not slot:
            continue
        bf_pct = slot.get("bf_pct")
        bw_kg = slot.get("_bw_kg")
        vat_g = slot.get("vat_g")
        fat_mass_kg = None
        lbm_kg = None
        if bf_pct is not None and bw_kg is not None:
            fat_mass_kg = round(bw_kg * bf_pct / 100.0, 3)
            lbm_kg = round(bw_kg - fat_mass_kg, 3)
        # Only emit a row if we actually have something measurable beyond
        # bodyweight alone — bodyweight without bf% / vat isn't enough to
        # populate any body_comp column (schema doesn't carry weight).
        if bf_pct is None and vat_g is None and fat_mass_kg is None:
            continue
        rows.append(
            {
                "date": d.isoformat(),
                "bf_pct": bf_pct,
                "lbm_kg": lbm_kg,
                "fat_mass_kg": fat_mass_kg,
                "vat_g": vat_g,
                "bmd": None,
                "source_file": xlsx_path.name,
            }
        )
    return rows
