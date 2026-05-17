"""Parse weekly sleep summaries into `sleep` rows.

We use `Sleep_Processed.xlsx` (cleaner time formats than `Sleep (1).csv` —
the CSV is the same underlying weekly data with formatting glitches) and
log-and-skip the CSV per CLAUDE.md §7. We also log-and-skip the standalone
*.png sleep summary images per the body-agent brief (no OCR).

The source row is *weekly*: a date range like "May 12-18", an Avg Duration
string ("6h 28min"), and a Column1 holding the duration in **minutes**. We
anchor each weekly aggregate at the Monday of that week and load it as one
`sleep` row with source = "Sleep Tracker Weekly". REM / deep / light / awake
breakdowns and heart-rate aren't in this source, so those columns stay NULL.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

SOURCE = "Sleep Tracker Weekly"

# Map abbreviated month names to integers; the spreadsheet uses standard
# 3-letter English month abbreviations.
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


def _parse_week_start(date_range, year: int) -> date | None:
    """Parse strings like 'May 12-18' or 'May 26 - Jun 1' to the start date.

    Returns the first day of the range as a `date` in the given `year`.
    Also accepts datetime / date values that Excel may have auto-converted
    when the entered string looked date-like (e.g. "Dec 29-31").
    """
    if isinstance(date_range, datetime):
        return date_range.date()
    if isinstance(date_range, date):
        return date_range
    if not isinstance(date_range, str):
        return None
    s = date_range.strip()
    # Form 1: "Mon DD-DD"
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2})\s*-\s*(\d{1,2})$", s)
    if m:
        mon, d_start, _d_end = m.group(1), int(m.group(2)), int(m.group(3))
        if mon in _MONTHS:
            try:
                return date(year, _MONTHS[mon], d_start)
            except ValueError:
                return None
    # Form 2: "Mon1 DD - Mon2 DD" (crosses month boundary)
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2})\s*-\s*([A-Za-z]+)\s+(\d{1,2})$", s)
    if m:
        mon1, d_start = m.group(1), int(m.group(2))
        if mon1 in _MONTHS:
            try:
                return date(year, _MONTHS[mon1], d_start)
            except ValueError:
                return None
    return None


def _minutes_from_duration(col1, dur_str) -> float | None:
    """Prefer the numeric `Column1` minutes; fall back to parsing the
    human-readable 'Xh Ymin' string if Column1 is missing.
    """
    try:
        m = float(col1)
        if m > 0:
            return m
    except (TypeError, ValueError):
        pass
    if isinstance(dur_str, str):
        m = re.match(r"\s*(\d+)\s*h\s*(\d+)\s*min", dur_str)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
        m = re.match(r"\s*(\d+)\s*h", dur_str)
        if m:
            return int(m.group(1)) * 60
    return None


def parse_sleep(xlsx_path: Path) -> list[dict]:
    df = pd.read_excel(xlsx_path, sheet_name="Sleep (1)")
    rows: list[dict] = []
    skipped = 0
    for _, r in df.iterrows():
        wk_start = _parse_week_start(r["Date"], int(r["Year"]))
        if wk_start is None:
            skipped += 1
            continue
        mins = _minutes_from_duration(r.get("Column1"), r.get("Avg Duration"))
        if mins is None:
            skipped += 1
            continue
        # Shift the Monday-of-week alignment: in practice Will's tracker weeks
        # start on Fridays per row 0 ("May 12-18" with May 12, 2023 being a
        # Friday), so we just take the literal first day of the range — the
        # week boundary is encoded by the source, not the calendar.
        rows.append(
            {
                "date": wk_start.isoformat(),
                "total_hr": round(mins / 60.0, 3),
                "rem_hr": None,
                "deep_hr": None,
                "light_hr": None,
                "awake_hr": None,
                "hr_avg": None,
                "source": SOURCE,
            }
        )
    if skipped:
        print(f"[body] sleep: skipped {skipped} unparseable rows in {xlsx_path.name}")
    return rows


def skip_csv_and_pngs(w_data: Path) -> list[str]:
    """Log-and-skip the redundant CSV and the *.png sleep images.

    Returns the list of source-file paths that were intentionally skipped so
    `ingest_meta` can record them.
    """
    skipped: list[str] = []
    csv_path = w_data / "Sleep (1).csv"
    if csv_path.exists():
        print(
            f"[body] sleep: SKIP {csv_path.name} — duplicate of "
            "Sleep_Processed.xlsx (same weekly aggregates)"
        )
        skipped.append(csv_path.name)
    for png in sorted(w_data.glob("*sleep.png")):
        print(
            f"[body] sleep: SKIP {png.name} — image-only summary, "
            "no paired CSV (no OCR per brief)"
        )
        skipped.append(png.name)
    return skipped
