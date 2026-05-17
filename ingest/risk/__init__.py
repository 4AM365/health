"""Risk agent — consumer-only.

Reads from labs / traits / pedigree / pedigree_conditions / body_comp.
Writes to one table: `risk_scores`. Also appends to `events` for dramatic
findings, and an `ingest_meta` row on completion.

See docs/VISION.md §1 and docs/SCHEMA.md §12.
"""
