"""Inspect Health.xlsx for any nutrition-shaped sheets and parse them.

As of this writing, Health.xlsx has these sheets, none of which are nutrition
logs (kcal/macros per day):

  - Physical Stats   -> body measurements (body agent)
  - FatOxRate        -> derived calorie-deficit projection spreadsheet
  - Bloodwork        -> bloodwork agent
  - To-Do            -> notes
  - Workout Volume   -> body agent

We inspect, print every sheet skipped with a reason, and return an empty
DataFrame so the contract stays simple. If a future revision of Health.xlsx
adds a daily-logged kcal sheet, extend the heuristic below.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pandas as pd

SOURCE = "health_xlsx"

# Header tokens that, if present in the first row of a sheet, mark it as a
# day-by-day nutrition log we can parse.
_NUTRITION_TOKENS = {"kcal", "calories", "protein", "carbs", "carb"}


def _looks_like_nutrition(headers: list[str]) -> bool:
    lowered = {h.lower() for h in headers if isinstance(h, str)}
    return bool(_NUTRITION_TOKENS & lowered)


def parse(path: Path) -> pd.DataFrame:
    """Return parsed daily nutrition rows from Health.xlsx, or empty df.

    Prints a one-line note for every sheet skipped + reason. Fails loud
    per CLAUDE.md §7.
    """
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    parsed_frames: list[pd.DataFrame] = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
        headers = [c for c in first_row if c is not None]

        if not _looks_like_nutrition(headers):
            print(
                f"  skip Health.xlsx[{sheet_name!r}]: "
                f"no nutrition header tokens (got {headers[:6]!r}...)"
            )
            continue

        # Future: parse the sheet here. Today, none exist.
        print(
            f"  Health.xlsx[{sheet_name!r}] looks nutrition-shaped but no "
            "parser implemented; skipping. Extend parse_health_xlsx.py."
        )

    wb.close()

    if not parsed_frames:
        return pd.DataFrame(
            columns=[
                "date",
                "kcal",
                "protein_g",
                "carb_g",
                "fat_g",
                "fiber_g",
                "sugar_g",
                "sodium_mg",
                "source",
                "source_file",
            ]
        )

    return pd.concat(parsed_frames, ignore_index=True)
