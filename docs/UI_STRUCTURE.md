# UI Structure

How the Streamlit dashboard is laid out and where the LLM appears inside it. Companion to [`LLM_INTERFACE.md`](LLM_INTERFACE.md) and [`USER_FLOW.md`](USER_FLOW.md). Owned by the **dashboard** agent under `app/`.

The dashboard is a single Streamlit process Will runs locally. It opens `analysis/health.db` read-only and renders one page at a time, with a persistent left rail and a persistent right rail.

---

## 1. Three-zone layout

```
┌──────────────┬──────────────────────────────────────┬──────────────┐
│              │                                      │              │
│   Left rail  │              Main pane               │  Right rail  │
│ (navigation) │           (the active view)          │  (LLM chat)  │
│              │                                      │              │
│   Home       │  ┌─────────────────────────────────┐ │  ┌─────────┐ │
│   Labs       │  │  View title + filters           │ │  │ context │ │
│   Nutrition  │  ├─────────────────────────────────┤ │  │ chip    │ │
│   Body       │  │  Chart(s)                       │ │  └─────────┘ │
│   Genome     │  │                                 │ │              │
│   Timeline   │  │  Tables                         │ │  ┌─────────┐ │
│   Ask  ●     │  │                                 │ │  │ user    │ │
│   Sources    │  │  [Ask about this view]  ←─────┐ │ │  │ msg     │ │
│              │  └─────────────────────────────│─┘ │ │  └─────────┘ │
│              │                                │   │ │              │
│              │                                ▼   │ │  ┌─────────┐ │
│              │                          opens chat│ │  │ assist. │ │
│              │                          panel ────┼─┼─►│ msg     │ │
│              │                          with view │ │  │ + cites │ │
│              │                          context   │ │  └─────────┘ │
│              │                                    │ │              │
│              │                                    │ │  [_____]send │
└──────────────┴────────────────────────────────────┴─┴──────────────┘
```

- **Left rail** is `st.sidebar`: page nav + a small "data freshness" indicator (when ingests last ran, from a `meta` table or file mtime).
- **Main pane** renders the active view module under `app/views/<name>.py`. One file per page.
- **Right rail** is the chat. It is **always visible** on every page. Width is collapsible so charts can take the full width on demand.

Putting chat on the right (instead of a dedicated Ask page only) makes the dashboard feel like *the data is the source of truth and the LLM annotates it*, not the other way around. A pure chat-first design pushes users to ask the model questions the dashboard could answer with a chart.

The Ask page (left rail) is still useful for **standalone exploration** — open in a fresh thread, no view context attached.

---

## 2. Pages

Each page is a single Python module under `app/views/`. Pages own their charts; they do not own LLM logic — they call into `app.llm` when the user invokes a chat action.

| Page | What it shows | Primary chart | "Ask about this" prefilled context |
|---|---|---|---|
| **Home** | Daily brief (LLM-generated, cached), 30-day quick-glance KPIs, recent events | KPI cards + sparkline strip | "Brief for {today}" |
| **Labs** | Bloodwork over time, ref-range bands, metric picker | Line per metric, with ref-low/high shaded | "Labs > {metric}, last {window}" |
| **Nutrition** | Macros + calories per day, rolling averages, micronutrient table | Stacked area for macros + line for kcal | "Nutrition, last {window}" |
| **Body** | DEXA snapshots, lifts (e1RM), sleep | Multi-row small-multiples | "Body, view = {DEXA\|lifts\|sleep}" |
| **Genome** | Derived traits grouped by category, plain-English notes | Tag cloud / table | "Trait: {trait}" |
| **Timeline** | Cross-domain `events` table with filters | Vertical timeline | "Events around {date}" |
| **Ask** | Full-window chat, no view scoping | n/a | (no context — fresh thread) |
| **Sources** | What files were ingested, when, row counts | Table | "Last ingest of {source}" |

**Home is the only page with a generated narrative.** Other pages stay deterministic; the LLM is invoked only when the user explicitly asks.

---

## 3. The chat panel

Three states:

1. **Idle.** Empty. A subtle "Ask about anything on this page" placeholder. No API calls made.
2. **Active, view-scoped.** Opened via "Ask about this view." A context chip at the top shows what's in scope (e.g. `Labs > HDL, last 24 months`). Chip is removable; removing it returns to general scope.
3. **Active, free.** Opened from the Ask page or after the user removes the context chip.

Within the panel, each assistant message has three parts:

- The text.
- A **citations strip** — small chips like `lab_series(HDL, 24mo)` · `correlate(HDL, fat_g, 24mo)`. Click a chip → main pane navigates to the corresponding view, filtered to those rows.
- A "regenerate" affordance — re-runs the same prompt with the same context, for when the user wants a second pass.

When the model is mid-stream, the panel shows a per-token streaming response and a small spinner next to whichever tool is currently executing (`get_lab_series` running…).

A red banner appears above the input field when the privacy filter has refused something. The banner explains *why*, not just *that*. ("That referenced raw rsid `rsXXXXX`. The LLM only sees derived traits. Try: 'what does my methylation trait look like?'")

---

## 4. Cross-page navigation from citations

The citations contract:

- Every tool that returns rows includes the parameters needed to deep-link back: `metric`, `since`, `until`, etc.
- The dashboard owns a small `app/routing.py` that maps `(tool_name, args) → (page, query_params)`.
- Clicking a citation chip sets the query params and switches pages. The destination page reads its filters from query params on load.

This is the mechanism that keeps the LLM honest: every claim is a link to the chart that backs it. A claim with no chart-shaped link is a claim the user can't verify, and they'll learn to distrust them.

---

## 5. Data freshness + ingest status

The dashboard never runs an ingest. It only reads `health.db`. But Will needs to know whether what he's looking at is stale.

Left-rail footer:

```
DB updated: 2026-05-15 22:11
Sources:
  bloodwork ✓ 2026-05-15
  nutrition ✓ 2026-05-15
  body      ✓ 2026-05-10
  sleep     ⚠ 2026-04-30 (16d)
  genome    ✓ 2026-02-01
```

Yellow `⚠` triggers when an expected-frequent source is stale relative to its cadence. The Sources page expands on this.

---

## 6. Settings (one screen, top-right gear)

Keep this small. Aggressive minimalism per [`../CLAUDE.md`](../CLAUDE.md) §3.

- LLM enabled (on/off, default off until API key present).
- Model: Opus 4.7 / Haiku 4.5 (default Opus).
- Daily brief: on/off, time-of-day.
- Privacy filter test button — runs the unit suite live and shows pass/fail.
- API key status (present / missing). Never displays the key itself.

No multi-user, no themes, no profile, no roles. One user, one machine.

---

## 7. Component inventory (the only reusable bits)

| Component | Purpose |
|---|---|
| `kpi_card(label, value, delta, sparkline)` | Home tiles |
| `series_chart(df, value_col, ref_low?, ref_high?)` | Labs, nutrition, body |
| `events_strip(df_events)` | Timeline + Home |
| `chat_panel(thread_state, context_chip?)` | Right rail |
| `citation_chip(tool, args, label)` | Inside assistant messages |
| `freshness_footer(ingest_meta)` | Sidebar footer |

Stop at this list. No design system, no shared CSS framework, no theming engine. Streamlit defaults plus a few `st.markdown` flourishes.

---

## 8. What's intentionally absent

- **No login screen.** Single-user, local.
- **No export/share buttons.** This is a private cockpit; nothing is meant to leave the laptop.
- **No notifications, no email, no Slack.** Push it and you're building a SaaS.
- **No "edit your data" UI.** Data flows in via ingests, not the dashboard. The dashboard is read-only.
- **No charts the LLM generates.** Charts are deterministic Python. The LLM annotates them; it doesn't draw them.
