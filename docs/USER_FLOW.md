# User Flow + Wargame

How Will (the sole user) actually moves through the dashboard, and where each path breaks. Companion to [`LLM_INTERFACE.md`](LLM_INTERFACE.md) and [`UI_STRUCTURE.md`](UI_STRUCTURE.md).

Two sections:
- **Part A — The happy path.** A typical session, end to end.
- **Part B — Wargame.** Adversarial walkthroughs. Each scenario describes what Will does, what *should* happen, where the design can fail, and the mitigation.

If a wargame entry has no satisfying mitigation, that's a bug in the design — flag it in [`CROSS_AGENT_NOTES.md`](CROSS_AGENT_NOTES.md) and fix here.

---

## Part A — The happy path

A typical Sunday-morning session. Will has just synced his weekly bloodwork PDF and a fresh MacroFactor export into `w_data/`.

```
1. Run ingests          (terminal, not in UI)
   $ python -m ingest.bloodwork
   $ python -m ingest.nutrition
   → health.db updated, last-ingest timestamps written

2. Launch dashboard
   $ streamlit run app/main.py
   → opens http://localhost:8501

3. Land on Home
   - sees daily brief (LLM, cached for today):
       "Your fasting glucose is up 8% over the last 30 days
        (95 → 103 mg/dL). HDL down 5%. Nutrition: ↑ carbs ↑ alcohol
        last 2 weeks. Sleep: −0.4 h/night vs your 90-day baseline.
        Worth flagging at next physical."
   - sees freshness footer: all green except sleep ⚠ (16d stale)

4. Click the glucose KPI card
   → main pane navigates to Labs > Fasting Glucose, 24mo window

5. Notices the recent uptick visually. Clicks "Ask about this view"
   → right rail opens with context chip: "Labs > Fasting Glucose, 24mo"
   → types: "what changed in my nutrition the week this trend started?"

6. LLM, tool-using:
   a. get_lab_series('glucose_fasting', since=2yr) → spots inflection ~2026-03
   b. get_nutrition_window(days=120) → daily macros around that date
   c. correlate('glucose_fasting', 'carb_g', 90)
   → assistant replies, citing each tool call as a clickable chip,
     ending with "discuss with provider."

7. Will clicks the citation chip for the nutrition tool call
   → main pane jumps to Nutrition, last 120 days, scrolled to March

8. Will closes the chat, browses, then opens it again on the Body page
   → fresh thread (per-page threads, no carry-over context)

9. Done. Will closes the tab. Streamlit session ends; chat threads gone.
   The DB persists; the next session starts cold.
```

Total LLM API calls in a session like this: ~1 for the cached daily brief (only if the brief for today doesn't exist), 1 per "Ask about this view" thread + N tool round-trips inside it. No background polling, no streaming when idle.

---

## Part B — Wargame

Eleven scenarios, ordered roughly worst-blast-radius to mildest.

### W1. "Tell me what's in Mattie's GEDCOM"

**What Will types:** "What hereditary risks does my daughter's GEDCOM suggest for her?"

**What should happen:** Privacy filter blocks the question before it touches the API. Red banner explains: this dashboard's pedigree data is in `private/` and is never sent to a cloud LLM; the LLM has no tool that reads it; even framing-only questions about minors' records are out of scope. Suggests Will use the Genome page directly for *his own* derived traits.

**Where it can fail:** Will rephrases as "what does my pedigree say about my own X." The pedigree table is sourced from `private/`. The model has no `get_pedigree` tool ([`LLM_INTERFACE.md`](LLM_INTERFACE.md) §3) — so even cleverly worded questions return nothing the LLM can ground on. Worst case: the LLM speculates from general knowledge. Mitigation: system prompt instructs "if no tool returned data, say so plainly; do not invent." Output filter additionally screens for any name from the pedigree table appearing in the response.

**Open risk:** If the schema agent ever exposes pedigree-derived fields through another table (e.g. a `family_history` column on `labs`), this protection silently weakens. Action: privacy unit tests must assert that no LLM-accessible tool returns data joined against `pedigree`.

---

### W2. "Just paste my rsids into the prompt"

**What Will types:** Pastes a block of `rs4988235 GG\nrs1801133 CT\n…` and asks "what do these mean?"

**What should happen:** Outbound privacy filter trips on the `rs\d+` pattern in the user message itself. Refuses to send. Banner explains and offers: "ask about the *trait*, not the raw genotype — e.g. 'what does my lactase persistence trait look like?'"

**Where it can fail:** Will mangles the rsids (`r_s4988235`, `RS4988235`, with spaces). Mitigation: the regex covers common variants, but is intentionally conservative — false positives are fine; false negatives are not. The deeper backstop: even if the regex misses, the LLM has no tool to *look up* an rsid, so it can only answer from general knowledge — which we want, because that's not a privacy breach (it's just published genetics).

**Action item for the genome agent:** any place where raw rsids are written into a UI element (e.g. a debug expander) needs to be off by default and not visible to "Ask about this view."

---

### W3. The LLM hallucinates a value

**What happens:** User asks "what was my highest fasting glucose this year?" Model replies "118 mg/dL on March 14" — but actual peak is 109. The 118 is invented.

**What should happen:** Every numeric claim is backed by a citation chip linking to `get_lab_series` or `get_lab_window_summary`. The user clicks the chip → main pane shows the actual data. Discrepancy is visible at a glance.

**Where it can fail:** User doesn't click the chip and acts on the wrong number. Mitigation: system prompt says "cite specific dates and values from tool results"; we additionally enforce a post-check that if the assistant's text contains any number that doesn't appear in *any* tool result it cited, flag with a warning footer ("⚠ value not found in cited data; please verify").

**Residual risk:** A confident-but-wrong narrative summary ("you're trending in the right direction") is harder to mechanically check. The mitigation is cultural: the daily brief always shows the actual numbers alongside the narrative, so contradiction is visible.

---

### W4. "Diagnose my fatigue"

**What Will types:** "I've been tired the last two weeks. What's wrong with me?"

**What should happen:** LLM gathers relevant data (sleep window, recent labs, nutrition macros, recent events) and produces a *non-diagnostic* synthesis ending with "discuss with provider." Suggested questions to take to that appointment.

**Where it can fail:** Model produces a confident differential diagnosis. Mitigation: system prompt explicitly forbids diagnosis. Post-check scans for diagnostic verbs ("you have X", "this is X") and appends or replaces with hedged language + the provider footer if missing.

**Residual risk:** Will treats the suggested questions as conclusions. Mitigation: copy in the chat panel (small, persistent): "Insights here are pattern-matching, not medicine."

---

### W5. API key missing or invalid

**What Will does:** Fresh laptop, no `ANTHROPIC_API_KEY` set. Opens the dashboard.

**What should happen:** Fail-loud at startup per [`../CLAUDE.md`](../CLAUDE.md) §7. The app doesn't crash — it loads normally, with the right rail in a "LLM disabled" state. Settings page shows missing key + instructions. Daily brief on Home is hidden (not stubbed). "Ask about this view" buttons are hidden. Sidebar shows a small "🤖 off" indicator.

**Where it can fail:** Will sees the dashboard, doesn't notice the LLM is off, complains about a "missing feature." Mitigation: the Home page, when LLM is off, replaces the daily brief slot with a single-line "Set `ANTHROPIC_API_KEY` to enable narrative briefs" with a link to Settings.

---

### W6. API down / rate-limited / timeout

**What happens mid-session:** User sends a chat message. API returns 529 / 429 / times out.

**What should happen:** Chat panel shows the error in line: "Anthropic API returned 529 (overloaded). Try again in a moment." A retry button. No silent fallback to a smaller model (would change the answer character without telling the user). No silent fallback to a "local" model (we don't have one).

**Where it can fail:** Mid-tool-call failure. The agent loop has already executed some tools, has results in memory, hits the API on the next turn, fails. The chat panel surfaces *what tools already ran* so Will can see what data was fetched even when the synthesis didn't complete.

---

### W7. Tool returns 50,000 rows

**What happens:** User asks a sloppy question, the model calls `get_nutrition_window(days=3650)`.

**What should happen:** Tools enforce a hard row cap (e.g. 500). On hit, the tool returns the first 500 plus a `truncated: true` field. System prompt teaches the model to recognize this and to either re-call with a narrower window or tell the user to narrow.

**Where it can fail:** Model ignores the `truncated` flag, summarizes from a partial slice as if it were the whole. Mitigation: when `truncated: true`, the post-processing layer injects "⚠ result truncated to 500 rows" into the assistant message *unconditionally*, not relying on the model to mention it.

---

### W8. User asks the LLM to do something it can't

**What Will types:** "Update my bloodwork to fix the date on that 2024 Quest test."

**What should happen:** The LLM has no write tools. It explains it can't, points to where the fix actually has to happen (the source CSV in `w_data/`, then re-run ingest).

**Where it can fail:** Model offers to *generate* an updated row and pretends it can save it. Mitigation: tools list in the system prompt is explicit and read-only-flavored ("get_*", "list_*", "correlate"). No tool name begins with `set_`, `write_`, `delete_`. The model has no surface to claim a write happened.

---

### W9. Stale DB

**What happens:** Will hasn't run ingests in 3 weeks. He opens the dashboard and the daily brief talks about "the last 30 days" using data that ends 21 days ago.

**What should happen:** Freshness footer in the sidebar shows yellow/red on stale sources. The daily brief prompt receives the freshness metadata and *opens with* a freshness statement: "Most recent data is 21 days old (2026-04-25). Run ingests for current view."

**Where it can fail:** Will misses the freshness line, acts on stale insight. Mitigation: when *any* source is more than 7 days stale, the Home page shows a persistent yellow banner above the brief, not just the sidebar footer.

---

### W10. Wrong-page citation

**What happens:** Assistant cites `get_traits(category='lipid_metabolism')`. User clicks the chip. The Genome page doesn't have a category filter built yet.

**What should happen:** Routing layer maps `(tool, args) → (page, query_params)`. If the destination page can't honor the args, it should display the unfiltered page with a non-blocking notice: "Filter `category=lipid_metabolism` requested but not yet supported on this page."

**Where it can fail:** The page silently ignores the filter and shows the unfiltered view, making the citation feel like a lie. Mitigation: explicit notice, not silent ignore. And keep the routing map and view-supported-filters list in one file so divergence is visible at code-review time.

---

### W11. Two browser tabs open

**What happens:** Will has the dashboard open in two tabs and sends a chat message in each.

**What should happen:** Streamlit gives each tab its own session state. Two independent chat threads. The DB is opened read-only in each — no contention.

**Where it can fail:** API key shared across tabs hits rate limits faster. Acceptable — single-user, low volume; rate limits aren't a real concern at n=1.

---

## Implications for the build

A few non-obvious requirements fall out of the wargame:

1. **Privacy tests are first-class.** `app/llm/tests/test_privacy_filter.py` must include all of W1, W2, and a test that asserts no LLM tool returns data joined against `pedigree`.
2. **Post-checks on assistant output are mandatory.** Diagnostic-verb check (W4), number-not-in-citations check (W3), truncation banner (W7).
3. **Citations are not decoration.** They are the *primary* mechanism for catching hallucination. Build them first, not last.
4. **Freshness is a first-class UI element**, not a debug field. (W9.)
5. **The LLM has no write surface, ever.** No tool name starting with a verb of mutation. (W8.)
6. **Fail loud on missing config, degrade gracefully on missing capability.** (W5.)

These aren't speculative requirements — each one ties to a wargame scenario above. If a future change removes any of them, it should reference the scenario it accepts as a regression.
