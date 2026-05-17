"""
Synthesis Pattern B (inflections) — tested against a fixture DB.

Per CLAUDE.md §6: synthesis is deterministic Python; unit tests live with
the synthesis layer, not the chart.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

from app import db as db_module
from app.synthesis import inflections, axes, counterfactual


SCHEMA_SQL = Path(__file__).parent.parent.parent.parent / "schema.sql"


@pytest.fixture
def fixture_db(tmp_path: Path, monkeypatch):
    """Build a tiny health.db at a temporary path with a synthetic lab
    series that has a clear inflection in the middle."""
    db_path = tmp_path / "health.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)

    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA_SQL.read_text())

    # 20 lab rows; first 10 around 100, last 10 around 130 — sharp jump.
    rows = []
    base = "2025-01-"
    for i in range(20):
        date = f"2025-{(i // 10) + 1:02d}-{(i % 10) + 1:02d}"
        value = 100.0 if i < 10 else 130.0
        rows.append((date, "Glucose", value, "mg/dL", 70.0, 99.0))
    con.executemany(
        "INSERT INTO labs (date, metric, value, unit, ref_low, ref_high) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    con.commit()
    con.close()
    yield db_path


def test_inflections_finds_jump(fixture_db):
    df = inflections.detect_inflections("Glucose", window=3, threshold_z=1.0)
    # We seeded a 30-point jump from ~100 to ~130; should find at least one inflection
    assert not df.empty
    assert any(row["delta"] > 0 for _, row in df.iterrows())


def test_inflections_empty_metric(fixture_db):
    df = inflections.detect_inflections("DoesNotExist", window=3)
    assert df.empty


def test_axes_handles_missing_data(tmp_path, monkeypatch):
    """No DB at all → axes return None values, don't crash."""
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "nonexistent.db")
    scores = axes.compute_all()
    assert len(scores) == 6
    for s in scores:
        assert s.value is None
        assert s.n_inputs == 0


def test_counterfactual_window_diff(fixture_db):
    """Pattern B (counterfactual): given an anchor date in the middle of
    the jump, the lab diff should show a positive delta."""
    df = counterfactual.window_diff(anchor="2025-02-01", window_days=30)
    glucose_rows = df[(df["domain"] == "labs") & (df["metric"] == "Glucose")]
    assert not glucose_rows.empty
    delta = glucose_rows.iloc[0]["delta"]
    assert delta is not None and delta > 0
