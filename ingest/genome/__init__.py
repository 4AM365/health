"""Genome ingest. Owns tables: snps, traits, pedigree, pedigree_conditions.

Privacy carve-outs (CLAUDE.md s8, AGENTS.md):
  - snps is NEVER exposed to the LLM (LLM_INTERFACE.md s3).
  - pedigree rows contain NO names. Relationship-coded only.
  - pedigree is sourced from gitignored private/. Skipped if absent.
"""
