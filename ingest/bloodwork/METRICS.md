# Bloodwork — Canonical Metrics

This file documents the canonical metric names written to `labs.metric` by the
bloodwork agent. **Convention**: lowercase snake_case, short form
(e.g. `hdl`, `ldl`, `total_cholesterol`). The full list is the single source of
truth at the top of [`metrics.py`](metrics.py); this file is the human-readable
narrative.

## Why short names

Long suffixes like `hdl_cholesterol_mg_dl` mix two things (analyte +
representation) into one identifier. We keep them separate:

- `metric` = what the analyte is (`hdl`)
- `unit` = how it's reported (`mg/dL`)

Filtering / charting becomes "all rows where `metric = 'hdl'`" regardless of
provider unit choices.

## Lipid panel + lipoprotein particles

| canonical | typical unit | sources |
|---|---|---|
| `total_cholesterol` | mg/dL | bloodwork.csv, SpectraCell PDFs |
| `triglycerides` | mg/dL | bloodwork.csv, SpectraCell PDFs |
| `hdl` | mg/dL | bloodwork.csv, SpectraCell PDFs |
| `ldl` | mg/dL | bloodwork.csv, SpectraCell PDFs |
| `non_hdl_cholesterol` | mg/dL | bloodwork.csv, SpectraCell PDFs |
| `vldl` | mg/dL | bloodwork.csv |
| `ldl_p` | nmol/L | bloodwork.csv, SpectraCell PDFs ("Total LDL Particles") |
| `vldl_p` | nmol/L | SpectraCell PDFs ("VLDL Particles") |
| `non_hdl_p` | nmol/L | bloodwork.csv ("Non HDL"), SpectraCell PDFs ("Non-HDL Particles") |
| `remnant_lipoprotein` | nmol/L | bloodwork.csv, SpectraCell PDFs |
| `dense_ldl_iii` | nmol/L | bloodwork.csv, SpectraCell PDFs |
| `dense_ldl_iv` | nmol/L | bloodwork.csv, SpectraCell PDFs |
| `hdl_p` | nmol/L | bloodwork.csv ("Total HDL"), SpectraCell PDFs ("Total HDL Particles") |
| `hdl_2b` | nmol/L | bloodwork.csv ("Buoyant HDL 2b"), SpectraCell PDFs |

> The Non-HDL gotcha: `bloodwork.csv` has both `Non HDL` (in nmol/L, a particle
> count) and `Non HDL Cholesterol` (in mg/dL, a cholesterol mass). They map to
> different canonical metrics — `non_hdl_p` vs `non_hdl_cholesterol`.

## Vascular inflammation

| canonical | typical unit |
|---|---|
| `insulin` | uIU/mL |
| `hs_crp` | mg/L |
| `lpa` | nmol/L (older reports) or mg/dL (newer SpectraCell) |
| `apo_b` | mg/dL |
| `apo_a1` | mg/dL |
| `homocysteine` | umol/L |

## Metabolic panel

| canonical | typical unit |
|---|---|
| `glucose` | mg/dL |
| `bun` | mg/dL |
| `creatinine` | mg/dL |
| `bun_creatinine_ratio` | ratio |
| `egfr` | mL/min/1.73m^2 |
| `sodium` | mmol/L |
| `potassium` | mmol/L |
| `chloride` | mmol/L |
| `co2` | mmol/L |
| `calcium` | mg/dL |
| `total_protein` | g/dL |
| `albumin` | g/dL |
| `globulin` | g/dL |
| `ag_ratio` | ratio |
| `total_bilirubin` | mg/dL |
| `alkaline_phosphatase` | U/L |
| `ast` | U/L |
| `alt` | U/L |

## CBC (Complete Blood Count)

| canonical | typical unit |
|---|---|
| `wbc` | x10E3/uL |
| `hemoglobin` | g/dL |
| `rbc` | x10E6/uL |
| `hematocrit` | % |
| `mcv` | fL |
| `mchc` | g/dL |
| `mch` | pg |
| `rdw` | % |
| `platelets` | x10E3/uL |
| `mpv` | fL |
| `lymphocytes_pct` | % |
| `lymphocytes_abs` | x10E3/uL |
| `neutrophils_pct` | % |
| `neutrophils_abs` | x10E3/uL |
| `monocytes_pct` | % |
| `monocytes_abs` | x10E3/uL |
| `eosinophils_pct` | % |
| `eosinophils_abs` | x10E3/uL |
| `basophils_pct` | % |
| `basophils_abs` | x10E3/uL |
| `immature_granulocytes_pct` | % |
| `immature_grans_abs` | x10E3/uL |

## Iron panel

| canonical | typical unit |
|---|---|
| `iron` | ug/dL |
| `tibc` | ug/dL |
| `ferritin` | ng/mL |

## Urinalysis (numeric only)

The labs table is numeric. Qualitative dipstick values
(`Leukocytes=Negative`, `Ketones=Trace`, etc.) are deliberately skipped — the
parser logs them with reason `"qualitative urinalysis (labs table is
numeric-only)"`. If they ever need to land in the DB, a separate
`labs_qualitative` table should be proposed via `docs/CROSS_AGENT_NOTES.md`
rather than overloading `labs.value`.

| canonical | typical unit |
|---|---|
| `urine_spec_grav` | (unitless) |
| `urine_ph` | pH |
| `urine_urobilinogen` | mg/dL |

## Not-in-scope (handled by other agents)

| label in source | canonical | owner |
|---|---|---|
| `Bodyweight` | `bodyweight` | body |
| `DEXA fat %` | `dexa_fat_pct` | body |
| `DEXA Visceral` | `dexa_visceral` | body |

These appear in `bloodwork.csv` because it's a master tracking sheet, but they
belong to the body agent's `body_comp` table.
