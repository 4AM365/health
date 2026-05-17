"""Entry point: python -m ingest.genome

Loads schema.sql if needed, then writes snps / traits / pedigree into
analysis/health.db. Idempotent per AGENTS.md (DELETE FROM <my> then INSERT).

Skips pedigree when private/ is absent and logs why (CLAUDE.md s7).
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from ingest.genome.parse_ancestry import (
    derive_traits_from_snps,
    load_panel,
    parse_ancestry_for_panel,
)
from ingest.genome.parse_choline import parse_choline_html
from ingest.genome.parse_gedcom import parse_gedcom_to_pedigree

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


REPO_ROOT = Path(__file__).resolve().parents[2]

ANCESTRY_PATH = REPO_ROOT / "w_data" / "2024 Data" / "wc-dna-data-2024-05-31" / "AncestryDNA.txt"
CHOLINE_HTML = REPO_ROOT / "w_data" / "Genetic Choline Calculator Results.html"
PURE_THERAPRO = REPO_ROOT / "w_data" / "Pure Therapro.png"
GEDCOM_PATH = REPO_ROOT / "private" / "craig_gedcom" / "Craig Family Tree.ged"
PANEL_YAML = Path(__file__).parent / "snp_panel.yaml"

SCHEMA_SQL = REPO_ROOT / "schema.sql"
DB_PATH = REPO_ROOT / "analysis" / "health.db"

SOURCE_ANCESTRY = "ancestrydna_2024_05_31"
SOURCE_CHOLINE = "masterjohn_choline_calc"
SOURCE_GEDCOM = "craig_gedcom"


def ensure_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not db_path.exists()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    if is_new:
        print(f"[genome] creating new DB at {db_path}")
        conn.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    return conn


def write_meta(
    conn: sqlite3.Connection,
    source: str,
    n_rows: int,
    source_file: str | None,
    notes: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO ingest_meta (source, last_run, n_rows, source_file, notes)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (source) DO UPDATE SET
            last_run = excluded.last_run,
            n_rows = excluded.n_rows,
            source_file = excluded.source_file,
            notes = excluded.notes
        """,
        (
            source,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            n_rows,
            source_file,
            notes,
        ),
    )


def run_snps_and_panel_traits(conn: sqlite3.Connection) -> None:
    if not ANCESTRY_PATH.exists():
        print(f"[genome] SKIP snps: AncestryDNA file not found at {ANCESTRY_PATH}")
        return

    panel = load_panel(PANEL_YAML)
    panel_rsids = {p.rsid for p in panel}
    print(f"[genome] panel size: {len(panel)} rsids")

    snps = parse_ancestry_for_panel(ANCESTRY_PATH, panel_rsids, SOURCE_ANCESTRY)
    missing = panel_rsids - {s.rsid for s in snps}
    if missing:
        print(f"[genome] panel rsids NOT on this chip: {sorted(missing)}")

    # Idempotent: clear snps + this-source's traits, then insert.
    conn.execute("DELETE FROM snps WHERE source = ?", (SOURCE_ANCESTRY,))
    conn.executemany(
        "INSERT INTO snps (rsid, chromosome, position, genotype, source) VALUES (?, ?, ?, ?, ?)",
        [(s.rsid, s.chromosome, s.position, s.genotype, s.source) for s in snps],
    )
    print(f"[genome] inserted {len(snps)} snps")

    traits = derive_traits_from_snps(snps, panel, SOURCE_ANCESTRY)
    # traits PK is (trait, source); upsert via INSERT OR REPLACE for idempotency.
    conn.execute("DELETE FROM traits WHERE source = ?", (SOURCE_ANCESTRY,))
    conn.executemany(
        """
        INSERT INTO traits (trait, category, value, source, confidence, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (t.trait, t.category, t.value, t.source, t.confidence, t.notes)
            for t in traits
        ],
    )
    print(f"[genome] inserted {len(traits)} derived traits from AncestryDNA panel")

    write_meta(
        conn,
        source=SOURCE_ANCESTRY,
        n_rows=len(snps),
        source_file=str(ANCESTRY_PATH.relative_to(REPO_ROOT)),
        notes=f"curated panel of {len(panel_rsids)} rsids; {len(snps)} found, {len(missing)} missing",
    )


def run_choline(conn: sqlite3.Connection) -> None:
    if not CHOLINE_HTML.exists():
        print(f"[genome] SKIP choline: HTML not found at {CHOLINE_HTML}")
        return

    traits = parse_choline_html(CHOLINE_HTML, SOURCE_CHOLINE)
    conn.execute("DELETE FROM traits WHERE source = ?", (SOURCE_CHOLINE,))
    conn.executemany(
        """
        INSERT INTO traits (trait, category, value, source, confidence, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (t.trait, t.category, t.value, t.source, t.confidence, t.notes)
            for t in traits
        ],
    )
    print(f"[genome] inserted {len(traits)} traits from Masterjohn choline calc")
    write_meta(
        conn,
        source=SOURCE_CHOLINE,
        n_rows=len(traits),
        source_file=str(CHOLINE_HTML.relative_to(REPO_ROOT)),
        notes="Masterjohn Genetic Choline Calculator results (HTML export)",
    )


def note_pure_therapro() -> None:
    """Pure Therapro.png is an image of a derived-trait report. OCR is out
    of scope (CLAUDE.md s6 - LLM/OCR not for parsing). Log the skip."""
    if not PURE_THERAPRO.exists():
        return
    print(
        f"[genome] SKIP pure_therapro: {PURE_THERAPRO.name} is a PNG image; "
        "OCR'ing derived-trait reports is out of scope. If a text version "
        "appears later, add a parser then."
    )


def run_pedigree(conn: sqlite3.Connection) -> None:
    if not GEDCOM_PATH.exists():
        print(
            f"[genome] SKIP pedigree: GEDCOM not found at {GEDCOM_PATH} "
            "(private/ likely not present in this worktree; this is fine)"
        )
        # Still clear any stale rows for this source so the DB reflects
        # current truth.
        conn.execute("DELETE FROM pedigree_conditions WHERE source = ?", (SOURCE_GEDCOM,))
        conn.execute("DELETE FROM pedigree WHERE source = ?", (SOURCE_GEDCOM,))
        write_meta(
            conn,
            source=SOURCE_GEDCOM,
            n_rows=0,
            source_file=None,
            notes="GEDCOM source not present this run",
        )
        return

    rows = parse_gedcom_to_pedigree(GEDCOM_PATH, SOURCE_GEDCOM)

    # Clear conditions first (FK), then pedigree.
    conn.execute("DELETE FROM pedigree_conditions WHERE source = ?", (SOURCE_GEDCOM,))
    conn.execute("DELETE FROM pedigree WHERE source = ?", (SOURCE_GEDCOM,))

    conn.executemany(
        """
        INSERT INTO pedigree (person_id, relationship, sex, birth_year, death_year, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (r.person_id, r.relationship, r.sex, r.birth_year, r.death_year, r.source)
            for r in rows
        ],
    )
    print(f"[genome] inserted {len(rows)} pedigree rows (name-free, relationship-coded)")

    # pedigree_conditions intentionally left empty initially - Will
    # populates over time. Per task spec.

    write_meta(
        conn,
        source=SOURCE_GEDCOM,
        n_rows=len(rows),
        source_file=None,  # never record private/ paths in the DB
        notes="GEDCOM (private/) -> name-free pedigree; conditions empty until populated",
    )


def main() -> int:
    print(f"[genome] starting ingest -> {DB_PATH}")
    conn = ensure_db(DB_PATH)
    try:
        run_snps_and_panel_traits(conn)
        run_choline(conn)
        note_pure_therapro()
        run_pedigree(conn)
        conn.commit()
    finally:
        conn.close()
    print("[genome] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
