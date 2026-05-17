"""
Health Repo Explorer — Streamlit interface.

Pages:
- Synthesis (Home): cross-domain narrative from health.db (or documented fallback).
- Overview: docs / scripts / data inventory while ingests are still landing.
- GEDCOM Stats: live run of scripts/gedcom_stats.py.
- SNP Panel: live run of scripts/snp_panel.py.
- Ancestor Verification: cached WikiTree cross-check report.

Run: streamlit run app/main.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent.parent
# Make the `app` package importable when streamlit runs this file directly.
sys.path.insert(0, str(ROOT))

from app import synthesis_data  # noqa: E402
from app.views import synthesis as synthesis_view  # noqa: E402

st.set_page_config(page_title="Health Repo Explorer", layout="wide")


@st.cache_data(show_spinner=False)
def run_script(*args: str, timeout: int = 120) -> tuple[str, str, int]:
    result = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout, result.stderr, result.returncode


# --------------------------------------------------------------------- sidebar

page = st.sidebar.radio(
    "View",
    [
        "Synthesis",
        "Overview",
        "GEDCOM Stats",
        "SNP Panel",
        "Ancestor Verification",
    ],
)
st.sidebar.markdown("---")
st.sidebar.caption("Read-only view of work on master.")

# --------------------------------------------------------------------- Synthesis

if page == "Synthesis":
    data = synthesis_data.load()
    if data.source != "db":
        st.sidebar.info(
            "Rendering documented fallback. "
            "Wire to `analysis/health.db` once the schema agent lands."
        )
    synthesis_view.render(data)

# --------------------------------------------------------------------- Overview

elif page == "Overview":
    st.title("Health Repo")
    st.caption(
        "Personal health intelligence dashboard — currently at the "
        "orchestration-scaffolding stage. No ingest pipeline or schema yet; "
        "what's runnable today is the three salvaged genome/pedigree scripts."
    )

    col_docs, col_scripts = st.columns(2)
    with col_docs:
        st.subheader("Docs")
        for p in sorted((ROOT / "docs").glob("*.md")):
            st.write(f"- `docs/{p.name}`")
        st.write(f"- `AGENTS.md` *(root)*")
        st.write(f"- `CLAUDE.md` *(root)*")
    with col_scripts:
        st.subheader("Scripts")
        for p in sorted((ROOT / "scripts").glob("*.py")):
            lines = sum(1 for _ in p.open(encoding="utf-8"))
            st.write(f"- `scripts/{p.name}` ({lines} lines)")

    st.subheader("Data sources")
    w_data = ROOT / "w_data"
    files = [f for f in w_data.rglob("*") if f.is_file()]
    size_mb = sum(f.stat().st_size for f in files) / 1e6
    st.write(
        f"**`w_data/`** (tracked, public): {len(files)} files, {size_mb:.1f} MB"
    )

    private = ROOT / "private"
    if private.exists():
        pfiles = [f for f in private.rglob("*") if f.is_file()]
        psize_mb = sum(f.stat().st_size for f in pfiles) / 1e6
        st.write(
            f"**`private/`** (gitignored): {len(pfiles)} files, "
            f"{psize_mb:.1f} MB — pedigree containing living minors"
        )
    else:
        st.warning("`private/` not found — GEDCOM-driven views will fail.")

    st.subheader("What's not built yet")
    st.write(
        "- `schema.sql` and `health.db` (Schema agent)\n"
        "- `ingest/bloodwork/`, `ingest/nutrition/`, `ingest/genome/`, "
        "`ingest/body/` (domain agents)\n"
        "- Full dashboard with charts and chat (Dashboard agent)"
    )

# --------------------------------------------------------------------- GEDCOM

elif page == "GEDCOM Stats":
    st.title("GEDCOM Statistics")
    st.caption("Live run of `scripts/gedcom_stats.py` against your pedigree.")
    ged = ROOT / "private" / "craig_gedcom" / "Craig Family Tree.ged"
    if not ged.exists():
        st.error(f"GEDCOM not found at `{ged.relative_to(ROOT)}`.")
        st.stop()

    with st.spinner("Parsing GEDCOM..."):
        stdout, stderr, rc = run_script("scripts/gedcom_stats.py")

    if rc == 0:
        st.code(stdout or "(no output)", language="text")
    else:
        st.error(f"Exited {rc}")
        if stderr:
            st.code(stderr, language="text")

# --------------------------------------------------------------------- SNP

elif page == "SNP Panel":
    st.title("Nutrient-Relevant SNP Panel")
    st.caption(
        "Live run of `scripts/snp_panel.py` against your AncestryDNA raw export. "
        "Hypothesis-generating only — evidence labels included per variant."
    )
    dna = ROOT / "w_data" / "2024 Data" / "wc-dna-data-2024-05-31" / "AncestryDNA.txt"
    if not dna.exists():
        st.error(f"AncestryDNA raw not found at `{dna.relative_to(ROOT)}`.")
        st.stop()

    with st.spinner("Scanning ~700k SNPs..."):
        stdout, stderr, rc = run_script("scripts/snp_panel.py")

    if rc == 0:
        st.code(stdout or "(no output)", language="text")
    else:
        st.error(f"Exited {rc}")
        if stderr:
            st.code(stderr, language="text")

# --------------------------------------------------------------------- Ancestor

elif page == "Ancestor Verification":
    st.title("Ancestor Verification (WikiTree cross-check)")
    st.caption(
        "Cross-references GEDCOM-claimed lifespans against WikiTree's public API "
        "to flag the conflated-record phantom-centenarian problem."
    )

    report = ROOT / "analysis" / "verification_report.json"

    if report.exists():
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except Exception as e:
            st.error(f"Cached report unreadable: {e}")
            st.stop()

        st.success(f"Loaded cached report — {len(data)} ancestors.")
        labels = Counter(d.get("label", "UNKNOWN") for d in data)
        cols = st.columns(len(labels))
        for col, (lbl, n) in zip(cols, sorted(labels.items(), key=lambda x: -x[1])):
            col.metric(lbl, n)
        st.dataframe(data, use_container_width=True)
    else:
        st.info(
            "No cached report at `analysis/verification_report.json`. "
            "Hit the button to run `scripts/verify_ancestors.py` — this calls "
            "the WikiTree API for each ancestor and may take several minutes."
        )
        if st.button("Run verification (slow)"):
            with st.spinner("Calling WikiTree API for each ancestor..."):
                stdout, stderr, rc = run_script(
                    "scripts/verify_ancestors.py", timeout=600
                )
            if rc == 0:
                st.success("Done. Reloading...")
                st.rerun()
            else:
                st.error(f"Exited {rc}")
                if stderr:
                    st.code(stderr, language="text")
