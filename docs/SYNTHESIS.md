# SYNTHESIS.md — Cross-Data Synthesis Philosophy

How to turn a database of personal health data into insights that change behavior.
Read this before adding any view to `app/` that crosses more than one domain.

This is the **why** layer above [`UI_STRUCTURE.md`](UI_STRUCTURE.md) (the *what* of the dashboard) and [`LLM_INTERFACE.md`](LLM_INTERFACE.md) (the *how* of the chat).

---

## 1. Eight principles

These are the rules the dashboard's analytic layer enforces. They are not aspirational; every cross-domain view in `app/views/` should be defensible against this list.

### P1. Triangulation over single-source signal
A reading from any one domain is a *hypothesis*. A hypothesis becomes a *signal* when independent domains agree.

- "HDL is falling" → hypothesis.
- "HDL is falling AND fat intake is up AND lifts volume is down AND sleep is short" → signal.

The dashboard should compute multi-source agreement scores per "axis of health" (metabolic, cardiovascular, inflammatory, hormonal, body composition, sleep). When 3+ domains converge, surface. When they disagree, *highlight the disagreement* — that's the more interesting story.

### P2. Personal baseline as ground truth
A clinical reference range is a population mean. An insight is a delta from *your own* history.

- A value at the 30th percentile of *your* trailing 5-year distribution is more interesting than the same value being "in range" clinically.
- Rolling z-scores against the user's own history beat ref-range banding for signal detection.

The reference range is still drawn (you need to know if you're crashing through the floor) but it is **not the primary visual** on a marker chart. The primary visual is the personal baseline band.

### P3. Trajectory > snapshot
Where you are matters less than where you're heading.

- A line is a fact.
- A slope is a question.
- An **inflection** is an event.

Run lightweight changepoint detection (e.g. PELT, BCP, or a simple rolling-mean crossover) on every continuous series. Inflections are first-class entities; the `events` table is where they land. The Timeline view renders them. The narrative LLM is told about them.

### P4. Contextualize with priors
The same lab number means different things at different risk profiles.

- LDL 130, APOE3/3, no family CVD → unremarkable.
- LDL 130, APOE4/4, two first-degree relatives MI'd before 60 → flag for Lp(a) test and provider conversation.

The dashboard's distinctive ability versus competitors: it has the **genome and the pedigree**. The synthesis layer must use them as priors that *upgrade or downgrade* the urgency of an otherwise-clinically-normal reading. This is the moat from [`VISION.md`](VISION.md).

### P5. Counterfactual the deltas
When a value moves, the question is always: *what was different in the period leading up to it?*

For every detected inflection (P3), automatically compute a "window diff":
- Window A = 60 days before the inflection
- Window B = 60 days after
- For each variable across **every** domain, compute the mean change
- Rank by absolute magnitude (z-scored, so units don't dominate)
- The top 3 deltas are the candidate causes

This is one of the few places n=1 data beats population studies. Population studies tell you the average effect of a variable; your own data tells you *your* response.

### P6. Actionability gating
Every surfaced insight must point to a decision:

- **Test** — get a specific lab/imaging done
- **Change** — adjust a specific behavior with a specific direction
- **Ask** — bring a specific question to the next provider visit
- **Monitor** — passive watch with a re-evaluation date

An insight without one of those four endings is noise. Strip it.

### P7. Hypothesis-not-diagnosis
n=1 personal health intelligence is **fundamentally hypothesis-generating**. The calibrated voice is:

- ✓ "Your data is consistent with X. Worth discussing with your provider."
- ✗ "You have X."
- ✓ "Pattern suggests Y is contributing."
- ✗ "Y is causing Z."

This is not just a copy rule — it's an architectural rule. The narrative LLM's system prompt enforces it; the post-check screens for diagnostic verbs ([`USER_FLOW.md`](USER_FLOW.md) W4).

### P8. Surface the unknown unknowns
The user doesn't know what to ask. A dashboard that only answers queries is a worse dashboard than one that *finds the user*.

The daily brief (Home page) is the primary "push" surface: it runs the synthesis pipeline overnight, picks the 2–3 most signal-rich observations, and renders them in plain English. The user doesn't have to know to look.

---

## 2. Synthesis patterns the dashboard implements

The principles above translate into a small number of reusable patterns. Each pattern is one analytical function + one rendering. Views compose patterns.

### Pattern A — Axis composites
For each "axis of health," compute a multi-source agreement score from the relevant domain signals.

**Metabolic axis example:**
| Signal | Source | Direction |
|---|---|---|
| Fasting glucose trend (90d) | `labs` | rising |
| HbA1c trend | `labs` | rising |
| HDL trend | `labs` | falling |
| Triglyceride trend | `labs` | rising |
| Visceral fat | `body_comp` (DEXA) | rising |
| Carb intake (rolling 30d) | `nutrition_daily` | rising |
| Fiber intake | `nutrition_daily` | falling |
| Sleep duration | `sleep` | falling |
| TCF7L2 / FTO variants | `traits` | risk-elevating (static prior) |
| First-degree T2DM in pedigree | `pedigree_conditions` | risk-elevating (static prior) |

The composite output is `{axis, signals: [...], agreement: 0..1, direction, n_supporting, n_dissenting, prior_weight}`. Six axes total: metabolic, cardiovascular, inflammatory, hormonal, body comp, sleep. The Home page renders these as six tiles, color-coded.

### Pattern B — Inflection detection + windowed counterfactual
For each continuous series in `labs`, `nutrition_daily`, `body_comp`, `sleep`:

1. Detect changepoints (PELT or rolling-window z-shift).
2. For each changepoint, compute window-A/window-B mean differentials across **every** variable in all domains.
3. Rank the top 3 deltas as candidate causes.
4. Write a row to `events` with `event_type='inflection'`, payload includes ranked candidates.

The marker view shows the inflection markers on the chart. Clicking one opens a side panel with the ranked candidates. This is Pattern E from [`USER_FLOW.md`](USER_FLOW.md)'s happy path operationalized.

### Pattern C — Gene-adjusted personal targets
YAML-declared per-nutrient calculators that read `snps` (or, preferably, `traits` — same data, derived view) and write `nutrient_targets`. Initial set per [`VISION.md`](VISION.md) §3:

- Choline (PEMT, CHDH) — Will already has the Masterjohn output
- Folate (MTHFR)
- Caffeine (CYP1A2)
- Alcohol (ALDH2, ADH1B)
- Lactose (LCT)
- Saturated fat tolerance (APOE)
- Iron (HFE)

Loader walks `analysis/calculators/*.yaml`, computes targets, writes table. Nutrition view shows actual intake vs personalized target, not the generic RDI.

### Pattern D — Pedigree-derived priors
For each top-killer condition (CVD, T2DM, Alzheimer's, breast cancer, prostate cancer, colon cancer):

- Count first-degree affected (parents, siblings, children)
- Median age of onset in pedigree
- Cause-of-death distribution if available
- Map condition → relevant labs (e.g., CVD → LDL, HDL, ApoB, Lp(a), CRP) and relevant SNPs (e.g., CVD → 9p21, APOE, LPA)

Pairs with Pattern A to compute "your CVD axis composite, given a pedigree prior of +1.4 std." Drives the urgency-elevation language in Pattern G narratives.

### Pattern E — Screening calendar overlay
`health_screening_schedule.xlsx` exists in `w_data/`. Parse it. For each recommended screening, compute "last done" from `labs` / `events` / a small `screenings` table. Surface overdue items in the daily brief.

This is the cheapest, highest-actionability insight type in the entire system: **"you haven't had a colonoscopy in 12 years; given your age and pedigree, schedule one."**

### Pattern F — Provider-conversation prep
On-demand button (Home page): generates a 1-page summary suitable for printing and bringing to a physical. Composed of:

- Top 3 axis composites (P-rated by agreement + magnitude)
- Top 3 detected inflections in the last 12 months
- Family-history flags (Pattern D)
- Overdue screenings (Pattern E)
- Open questions the LLM-generated narratives flagged across the last N daily briefs

This is the artifact a non-clinician user actually *uses*. The dashboard's distinctive output.

### Pattern G — Narrative synthesis (LLM, bounded)
The daily brief + the "Ask about this view" responses are LLM-generated, but they consume the outputs of Patterns A–F, not the raw tables. The LLM is a *narrator* of the synthesis, not the synthesizer.

This is the [`CLAUDE.md`](../CLAUDE.md) §6 rule operationalized: deterministic Python computes the signals, the LLM writes the paragraph.

---

## 3. Anti-patterns

Things that *look* like cross-data synthesis but aren't and shouldn't ship:

- **Correlation matrices without controls.** "HDL correlates with sleep at r=0.3" is meaningless across 5 years of seasonal/age trends. Always state the window, the n, and the dominant covariate.
- **Single-variable narratives.** "Your fiber is low" is not synthesis. "Your fiber is low AND your LDL is rising AND you have a CVD-leaning pedigree AND a non-tolerant APOE genotype" is.
- **Heat-mapping everything.** Most heat maps over n=1 data are visual noise. Use only when there are ≥3 categorical dimensions and the cell magnitude is interpretable.
- **PRS-only "your risk is..."** Polygenic scores are population-calibrated. They are *one* prior, not the whole story. Always pair with pedigree, current labs, and behavior.
- **Recommendations the user can't act on.** "Your VLDL particle count subspecies pattern suggests..." — if Will can't change behavior or ask a doctor a specific question on the basis of it, it's noise.

---

## 4. Where this lives in code

| Layer | Module |
|---|---|
| Axis composite computation | `app/synthesis/axes.py` |
| Inflection detection | `app/synthesis/inflections.py` |
| Window-diff counterfactual | `app/synthesis/counterfactual.py` |
| Calculator loader (YAML → `nutrient_targets`) | `app/synthesis/calculators.py` |
| Pedigree priors | `app/synthesis/priors.py` |
| Screening overlay | `app/synthesis/screening.py` |
| Provider summary builder | `app/synthesis/provider_summary.py` |
| Daily brief composer | `app/llm/brief.py` (consumes the above) |

The synthesis layer is **deterministic**. It computes scores, ranks, and structured outputs. The LLM layer narrates over the synthesis layer's outputs. This split is the privacy boundary (P7 + [`LLM_INTERFACE.md`](LLM_INTERFACE.md) §4) and the testability boundary — synthesis has unit tests, narration has eyeballs.

---

## 5. Test the synthesis, not the chart

A unit test of `axes.compute_metabolic(...)` against a fixture DB asserts the agreement score, the ranked signals, and the prior weight. That's the test of value — *the synthesis was right*. Charts can be wrong in ways tests catch poorly; synthesis can't.

This means: every view that renders Pattern A–F output has a corresponding fixture test of the underlying function. If a view changes, the test doesn't. If the synthesis logic changes, the view doesn't need updating.
