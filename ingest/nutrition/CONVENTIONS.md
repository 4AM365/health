# Nutrition ingest conventions

What the nutrition agent assumes about each source. If a future source breaks
one of these, document the exception here and adjust the parser — don't
silently coerce.

## MacroFactor CSV (`w_data/MacroFactor-*.csv`)

- One row per logged food item, with `Date` (`YYYY-MM-DD`) and `Time` columns.
- We aggregate to per-day totals via `groupby('Date').sum()` over:
  - `Calories (kcal)` -> `kcal`
  - `Protein (g)` -> `protein_g`
  - `Carbs (g)` -> `carb_g`
  - `Fat (g)` -> `fat_g`
  - `Fiber (g)` -> `fiber_g`
  - `Sugars (g)` -> `sugar_g`
  - `Sodium (mg)` -> `sodium_mg`
- Macros are in grams, kcal in kcal, sodium in mg. No unit conversions needed.
- **Carb convention:** MacroFactor's `Carbs (g)` is total carbohydrate
  (includes fiber). We pass that through to `carb_g` and store fiber
  separately in `fiber_g`. Consumers wanting net carbs compute
  `carb_g - fiber_g`.
- Blank cells for unmeasured nutrients become `NaN` -> SQL `NULL` after
  `pd.to_numeric(..., errors='coerce')` + `.sum(min_count=1)`.
- The export contains a long tail of recent days with only a token entry
  (e.g. one item logged); these become low-kcal days and are written as-is.
  Fail-loud rule: we do not invent data or filter days; if Will logged
  only 20 kcal, the dashboard shows 20 kcal.

## Health.xlsx

- Inspected on each run. As of this commit, **no sheet in `Health.xlsx` is a
  daily nutrition log** — the spreadsheet holds physical stats, bloodwork,
  fat-oxidation calculations, a to-do list, and workout volume, all of which
  belong to other agents. The parser prints each skipped sheet + reason
  and writes zero rows.
- If a future revision adds a per-day kcal/macro sheet, extend
  `parse_health_xlsx.py` to handle it (the header-token heuristic will
  pick it up).

## `nutrition_daily` PK

- `(date, source)`. Multiple sources can co-exist for the same date. The
  dashboard chooses which to render.
