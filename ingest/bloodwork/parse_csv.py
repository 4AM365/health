"""CSV parsers for the bloodwork agent.

Two files are handled here:

1. `w_data/bloodwork.csv` — Will's longitudinal master sheet. Wide-format:
     row 0:  [_, _, date1, date2, date3, date4, date5, _, _]
     rows:   [section?, metric, v1, v2, v3, v4, v5, unit?, notes?]
   One INSERT per (date, metric) where the value cell is non-empty and numeric.

2. `w_data/Blood_Test_Results.csv` — A four-column Quest/Labcorp dump:
     Test Name, Value, Unit, Normal Range
   The file has **no date**. Values exactly match the 11/29/2023 column in
   `bloodwork.csv`, so the data is already covered there — we skip this file
   loudly per CLAUDE.md §7 (fail loud, don't fabricate dates).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ingest._shared.dates import to_iso
from ingest.bloodwork.metrics import (
    canonical_metric,
    normalize_unit,
    parse_range,
)


@dataclass
class LabRow:
    date: str
    metric: str
    value: float
    unit: str | None
    ref_low: float | None
    ref_high: float | None
    source_file: str
    lab_provider: str | None
    notes: str | None


@dataclass
class ParseResult:
    rows: list[LabRow]
    skipped_labels: list[tuple[str, str]]   # (label, reason)
    skipped_values: list[tuple[str, str, str]]  # (date, label, raw_value) — non-numeric


def _parse_value(raw: str) -> float | None:
    s = str(raw).strip()
    if not s:
        return None
    # Tolerate stray commas/units that occasionally leak into the cell
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_bloodwork_csv(path: Path) -> ParseResult:
    """Parse the wide-format `bloodwork.csv` master sheet."""
    rows: list[LabRow] = []
    skipped_labels: list[tuple[str, str]] = []
    skipped_values: list[tuple[str, str, str]] = []
    source_file = path.name

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = list(csv.reader(f))

    if not reader:
        return ParseResult([], [], [])

    header = reader[0]
    # Date columns are 2..6 in the layout we documented.
    date_cols = list(range(2, 7))
    dates: list[str | None] = []
    for c in date_cols:
        if c < len(header):
            dates.append(to_iso(header[c]))
        else:
            dates.append(None)

    for row in reader[1:]:
        # pad row to expected length
        while len(row) < 9:
            row.append("")
        section, label, *_rest = row
        unit_raw = row[7] if len(row) > 7 else ""
        notes_raw = row[8] if len(row) > 8 else ""

        if not label.strip():
            continue

        metric, reason = canonical_metric(label)
        if metric is None:
            skipped_labels.append((label, reason or "unknown"))
            continue

        unit = normalize_unit(unit_raw) if unit_raw else None
        notes = notes_raw.strip() or None
        # Reference range can sometimes be embedded in notes ("Target <700"),
        # but the schema's ref_low/ref_high are for hard clinical ranges. Leave
        # them None here and stash the literal text in notes.
        ref_low, ref_high = (None, None)

        for di, date in enumerate(dates):
            if date is None:
                continue
            cell = row[date_cols[di]] if date_cols[di] < len(row) else ""
            if cell.strip() == "":
                continue
            val = _parse_value(cell)
            if val is None:
                skipped_values.append((date, label, cell))
                continue
            rows.append(LabRow(
                date=date,
                metric=metric,
                value=val,
                unit=unit,
                ref_low=ref_low,
                ref_high=ref_high,
                source_file=source_file,
                lab_provider=None,
                notes=notes,
            ))

    return ParseResult(rows, skipped_labels, skipped_values)


def explain_blood_test_results_csv(path: Path) -> str:
    """`Blood_Test_Results.csv` has no date column. Document why we skip it.

    Cross-checked manually against `bloodwork.csv`: WBC=8.1, Hgb=14.9, RBC=5.11
    etc. all match the `11/29/2023` column in the master sheet, so the data is
    already represented. Fabricating a date here would violate CLAUDE.md §7.
    """
    return (
        f"{path.name}: file has no date column; values match the 11/29/2023 "
        "panel already loaded from bloodwork.csv. Skipping to avoid duplicates."
    )
