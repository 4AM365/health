"""Parse the strength-training log spreadsheet into `lifts` rows.

The 2025 Lifts.xlsx layout is a hand-maintained grid:
  - Column 0 names the "Day" block (Upper A / Lower A / Upper B / Lower B).
  - Column 1 holds the exercise name.
  - Column 2 holds prescribed sets x reps (parsed only for `sets`).
  - Above each Day block, one or two header rows place session dates over
    column pairs (weight, reps). For block "Upper A" the dates live in row 0
    AND row 2; for the other blocks the dates live in the single row
    immediately above the block.

We accept only numeric (weight, reps) pairs. Anything that's a free-text
annotation (e.g. "10 dbs", "running", "sick...") is logged-and-skipped per
CLAUDE.md §7. Weights in the sheet are pounds; we convert to kg. e1RM uses
Epley: weight * (1 + reps/30).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

LB_TO_KG = 0.453592


def _as_int(x) -> int | None:
    try:
        i = int(x)
        return i if i > 0 else None
    except (TypeError, ValueError):
        return None


def _as_date(x) -> date | None:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return None


def _sets_from_scheme(scheme) -> int | None:
    """Parse '3x6x8' / '3x12' style prescription strings to get the sets count.

    The sheet uses a non-ASCII multiplication character; we handle it
    generically by taking the leading integer.
    """
    if not isinstance(scheme, str):
        return None
    head = ""
    for ch in scheme:
        if ch.isdigit():
            head += ch
        else:
            break
    return int(head) if head else None


def parse_lifts(xlsx_path: Path) -> list[dict]:
    raw = pd.read_excel(xlsx_path, sheet_name=0, header=None)
    # Identify Day-block starts: rows where col 0 is a non-empty string that
    # isn't the literal "Day" header.
    block_starts: list[int] = []
    for i, val in enumerate(raw[0]):
        if isinstance(val, str) and val.strip() and val.strip() != "Day":
            block_starts.append(i)

    skipped = 0
    rows_out: list[dict] = []
    n_rows = len(raw)
    n_cols = raw.shape[1]

    for bi, start in enumerate(block_starts):
        end = block_starts[bi + 1] if bi + 1 < len(block_starts) else n_rows
        # Search upward from `start` to the previous block's last row (or 0)
        # for any rows that contain dates; build col -> date map.
        prev_end = block_starts[bi - 1] + 1 if bi > 0 else 0
        col_to_date: dict[int, date] = {}
        for hr in range(prev_end, start):
            for c in range(n_cols):
                d = _as_date(raw.iat[hr, c])
                if d is not None:
                    col_to_date[c] = d

        if not col_to_date:
            print(
                f"[body] lifts: SKIP block at row {start} "
                f"({raw.iat[start, 0]!r}) — no session dates found above it"
            )
            continue

        # Iterate exercises in this block.
        for r in range(start, end):
            exercise = raw.iat[r, 1]
            if not isinstance(exercise, str) or not exercise.strip():
                continue
            scheme = raw.iat[r, 2]
            n_sets = _sets_from_scheme(scheme) if isinstance(scheme, str) else None

            for wcol, sess_date in col_to_date.items():
                rcol = wcol + 1
                if rcol >= n_cols:
                    continue
                w_raw = raw.iat[r, wcol]
                r_raw = raw.iat[r, rcol]
                # Need numeric weight and numeric reps to compute e1RM.
                try:
                    w_lb = float(w_raw)
                except (TypeError, ValueError):
                    if pd.notna(w_raw) and not (isinstance(w_raw, str) and not w_raw.strip()):
                        skipped += 1
                    continue
                reps = _as_int(r_raw)
                if reps is None:
                    if pd.notna(r_raw):
                        skipped += 1
                    continue
                # Treat bodyweight-only entries (weight==0) as skip with note —
                # they happen for split squats etc. They don't carry an e1RM
                # signal worth tracking in the same table as loaded lifts.
                if w_lb <= 0:
                    skipped += 1
                    continue

                weight_kg = round(w_lb * LB_TO_KG, 3)
                e1rm = round(weight_kg * (1 + reps / 30.0), 3)
                rows_out.append(
                    {
                        "date": sess_date.isoformat(),
                        "lift": exercise.strip(),
                        "weight_kg": weight_kg,
                        "reps": reps,
                        "sets": n_sets,
                        "e1rm": e1rm,
                        "source_file": xlsx_path.name,
                    }
                )

    if skipped:
        print(f"[body] lifts: skipped {skipped} non-numeric cells (annotations / 0-weight)")
    return rows_out
