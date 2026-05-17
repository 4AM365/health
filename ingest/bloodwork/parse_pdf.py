"""PDF parser for SpectraCell-style lab reports.

Both `Craig,William10212025.pdf` and `-279-00022-241005.pdf` are SpectraCell
tabular reports with this consistent layout:

- The specimen header table contains `DATE COLLECTED` in MM/DD/YYYY form.
- Result tables have columns: [Test, '', In Range, Out of Range, Reference Range, Units].
  Each row's value lives in **either** "In Range" or "Out of Range" — never both.
  We pull whichever cell is non-empty.

If a PDF has no extractable text (image-only scan), we log + skip rather than
guess. The `2025.pdf` in `w_data/` is one such scan.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from ingest._shared.dates import to_iso
from ingest.bloodwork.metrics import (
    canonical_metric,
    normalize_unit,
    parse_range,
)


_RESULT_HEADER = ("Tests", "")  # first two cells of every result table


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
    skip_file_reason: str | None = None     # set when the whole file is unusable


_MDY = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")


def _find_date_collected(pdf: pdfplumber.PDF) -> str | None:
    """Pull `DATE COLLECTED` MM/DD/YYYY from the SpectraCell specimen header.

    Strategy: scan tables on each page for one whose flattened text contains
    `DATE COLLECTED`. The collected date is the **second** MM/DD/YYYY in that
    block (the first being DOB or an unrelated date depends on layout). In
    practice on every SpectraCell PDF in this repo, the collected date is the
    earliest date after the literal "DATE COLLECTED" header.
    """
    for page in pdf.pages:
        for table in page.extract_tables() or []:
            flat = " ".join(
                str(c) for row in table for c in row
                if c is not None
            )
            if "DATE COLLECTED" not in flat:
                continue
            # Look at substring after the header
            tail = flat.split("DATE COLLECTED", 1)[1]
            for m in _MDY.finditer(tail):
                iso = to_iso(m.group(1))
                if iso:
                    return iso
    # Fallback: scan page text
    for page in pdf.pages:
        text = page.extract_text() or ""
        if "DATE COLLECTED" not in text:
            continue
        tail = text.split("DATE COLLECTED", 1)[1]
        for m in _MDY.finditer(tail):
            iso = to_iso(m.group(1))
            if iso:
                return iso
    return None


def _parse_value(raw: str) -> float | None:
    s = (raw or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _iter_result_rows(pdf: pdfplumber.PDF):
    """Yield raw result-table rows from a SpectraCell PDF."""
    for page in pdf.pages:
        for table in page.extract_tables() or []:
            if not table:
                continue
            head = table[0]
            if len(head) >= 2 and head[0] == _RESULT_HEADER[0] and head[1] == _RESULT_HEADER[1]:
                for r in table[1:]:
                    yield r
            elif len(table) == 1 and table[0] and len(table[0]) >= 6:
                # SpectraCell occasionally renders a single-row continuation
                # table (e.g. "Non-HDL Cholesterol" alone on page 3). Same
                # 6-column shape as the result tables.
                r = table[0]
                if any(_parse_value(c) is not None for c in r[2:4]):
                    yield r


def parse_spectracell_pdf(path: Path) -> ParseResult:
    rows: list[LabRow] = []
    skipped: list[tuple[str, str]] = []
    source_file = path.name

    with pdfplumber.open(path) as pdf:
        # Image-only scan check: if every page has no text, this is OCR'd or
        # imaged. We don't OCR here — log + skip per CLAUDE.md §6/§7.
        text_lengths = [len(p.extract_text() or "") for p in pdf.pages]
        if sum(text_lengths) == 0:
            return ParseResult(
                rows=[],
                skipped_labels=[],
                skip_file_reason="no extractable text (image-only / scanned PDF)",
            )

        date_iso = _find_date_collected(pdf)
        if not date_iso:
            return ParseResult(
                rows=[],
                skipped_labels=[],
                skip_file_reason="could not locate `DATE COLLECTED` in PDF text",
            )

        for r in _iter_result_rows(pdf):
            # pad
            while len(r) < 6:
                r.append("")
            label, _, in_range, out_range, ref_range, unit_raw = r[:6]
            if not (label or "").strip():
                continue
            # Pick value from whichever cell is filled.
            value_raw = (in_range or "").strip() or (out_range or "").strip()
            val = _parse_value(value_raw)
            if val is None:
                # Some rows in result tables are commentary / non-numeric
                # (e.g. "Metabolic Syndrome Traits" -> "Zero"). Skip them.
                skipped.append((label, f"non-numeric value: {value_raw!r}"))
                continue
            metric, reason = canonical_metric(label)
            if metric is None:
                skipped.append((label, reason or "unknown"))
                continue
            ref_low, ref_high = parse_range(ref_range)
            unit = normalize_unit(unit_raw)
            rows.append(LabRow(
                date=date_iso,
                metric=metric,
                value=val,
                unit=unit,
                ref_low=ref_low,
                ref_high=ref_high,
                source_file=source_file,
                lab_provider="SpectraCell",
                notes=None,
            ))

    return ParseResult(rows=rows, skipped_labels=skipped)
