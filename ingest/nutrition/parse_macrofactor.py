"""Parse MacroFactor CSV export into daily nutrition rows.

MacroFactor exports one row per logged food item with a Date column (YYYY-MM-DD)
and per-item macros. We aggregate to daily totals: sum kcal + macros + sodium
+ fiber + sugars over all items for each date.

Conventions documented in `ingest/nutrition/CONVENTIONS.md`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

SOURCE = "macrofactor"

# MacroFactor CSV column -> nutrition_daily field.
_COLS = {
    "Calories (kcal)": "kcal",
    "Protein (g)": "protein_g",
    "Carbs (g)": "carb_g",
    "Fat (g)": "fat_g",
    "Fiber (g)": "fiber_g",
    "Sugars (g)": "sugar_g",
    "Sodium (mg)": "sodium_mg",
}


def parse(path: Path) -> pd.DataFrame:
    """Return a DataFrame of daily rows matching `nutrition_daily` schema.

    Columns: date, kcal, protein_g, carb_g, fat_g, fiber_g, sugar_g,
    sodium_mg, source, source_file.
    """
    df = pd.read_csv(path)

    missing = [c for c in _COLS if c not in df.columns]
    if missing:
        raise ValueError(
            f"MacroFactor CSV {path.name} missing expected columns: {missing}"
        )

    if "Date" not in df.columns:
        raise ValueError(f"MacroFactor CSV {path.name} missing 'Date' column")

    # Coerce numerics; MacroFactor leaves blanks for unmeasured nutrients.
    for csv_col in _COLS:
        df[csv_col] = pd.to_numeric(df[csv_col], errors="coerce")

    daily = (
        df.groupby("Date", as_index=False)[list(_COLS.keys())]
        .sum(min_count=1)
        .rename(columns={"Date": "date", **_COLS})
    )

    daily["source"] = SOURCE
    daily["source_file"] = path.name

    return daily[
        [
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
    ]
