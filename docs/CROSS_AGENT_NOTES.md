# CROSS_AGENT_NOTES.md

Append-only scratchpad for out-of-lane observations. Don't edit others' entries.
Format: `## YYYY-MM-DD [<agent>] <topic>` then body.

---

## 2026-05-16 [body] body_comp.bmd column semantics

The DEXA report we have (`William Craig 3-3-22 Dexa Body Composition Report
v2024.pdf`) does NOT print a raw BMD value in g/cm². It only prints the
T-Score (0.8) and Z-Score (0.4). The body parser stores the T-Score in the
`bmd` column because that's the most actionable signal for the dashboard.
Schema agent: consider renaming `body_comp.bmd` to `bmd_t_score`, or adding a
separate `bmd_z_score` column. Dashboard agent: when displaying `bmd`, treat
values in roughly the range -3.0 .. +3.0 as a T-score, not a density.

## 2026-05-16 [body] DEXA visceral fat units

The DEXA PDF reports "Visceral Fat Pounds" (0.97 lb in the 2022 scan). The
Bloodwork sheet in `Health.xlsx` also stores visceral fat in pounds (1.0 lb,
0.5 lb). The body parser converts to grams (`vat_g`) as the schema requires.
For reference: 0.97 lb -> ~440 g; 1.0 lb -> ~454 g; 0.5 lb -> ~227 g.

## 2026-05-16 [body] Health.xlsx ownership

`Health.xlsx` is a catch-all shared across domains. The body parser reads
only the first three rows of the **Bloodwork** sheet (Bodyweight, DEXA
fat %, DEXA Visceral). The rest of the Bloodwork sheet (rows 8+: Iron,
TIBC, lipid panel, etc.) is bloodwork-owned and we don't touch it. The
**FatOxRate** sheet holds calorie-budgeting data that's nutrition-shaped;
nutrition agent may want to inspect it.
