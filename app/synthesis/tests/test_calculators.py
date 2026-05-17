"""
Synthesis Pattern C (calculators) — load YAML, join to snps, write
nutrient_targets. Tested with a fixture DB.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app import db as db_module
from app.synthesis import calculators


SCHEMA_SQL = Path(__file__).parent.parent.parent.parent / "schema.sql"


@pytest.fixture
def fixture_db_with_snps(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "health.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA_SQL.read_text())
    # Seed the SNPs used by choline.yaml
    con.executemany(
        "INSERT INTO snps (rsid, chromosome, position, genotype, source) VALUES (?, ?, ?, ?, ?)",
        [
            ("rs7946",     "17", 17409561, "TT", "test"),   # PEMT homozygote effect
            ("rs12325817", "12", 111062446, "GG", "test"),  # CHDH homozygote effect
            ("rs1801133",  "1", 11854476, "CT", "test"),    # MTHFR heterozygous
            ("rs1801131",  "1", 11854488, "AA", "test"),    # MTHFR no effect
            ("rs762551",   "15", 75041917, "AC", "test"),   # CYP1A2 heterozygous (1 C)
        ],
    )
    con.commit()
    con.close()
    yield db_path


def test_choline_calc_runs_and_writes(fixture_db_with_snps):
    results = calculators.run(sex="male")
    # Find the choline result
    choline = next((r for r in results if r.nutrient == "choline_mg"), None)
    assert choline is not None
    # base 550 + (2*50) for TT on rs7946 + (2*100) for GG on rs12325817 = 850
    assert choline.target_value == pytest.approx(850.0)

    # Verify it was written to nutrient_targets
    con = sqlite3.connect(fixture_db_with_snps)
    cur = con.execute(
        "SELECT target_value FROM nutrient_targets WHERE nutrient = 'choline_mg'"
    )
    row = cur.fetchone()
    assert row is not None
    assert row[0] == pytest.approx(850.0)
    con.close()


def test_folate_calc(fixture_db_with_snps):
    results = calculators.run()
    folate = next((r for r in results if r.nutrient == "folate_mcg"), None)
    assert folate is not None
    # base 400 + (1*100) for CT on rs1801133 + (0*50) for AA on rs1801131 = 500
    assert folate.target_value == pytest.approx(500.0)


def test_caffeine_calc_negative_increment(fixture_db_with_snps):
    """CYP1A2 rs762551 — each C allele LOWERS the ceiling."""
    results = calculators.run()
    caf = next((r for r in results if r.nutrient == "caffeine_mg_ceiling"), None)
    assert caf is not None
    # base 400 + (1 * -100) for AC = 300
    assert caf.target_value == pytest.approx(300.0)


def test_calc_no_db(tmp_path, monkeypatch):
    """No DB at all → calculators don't crash; they just return empty."""
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "nonexistent.db")
    # Without the snps lookups, all calculators still run on base RDIs.
    results = calculators.run()
    # Each YAML produces a result with target == base_rdi
    nutrients = {r.nutrient: r.target_value for r in results}
    assert "choline_mg" in nutrients
    # base male is 550 (default sex=None means cfg["base_rdi"] = 550)
    assert nutrients["choline_mg"] == 550.0
