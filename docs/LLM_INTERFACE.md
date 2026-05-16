# LLM Interface

How a cloud LLM (Claude) is wired into the dashboard so Will can ask free-text questions over his own data without breaching the project's privacy rules.

This is a **design doc**. Owner-on-implementation is the **dashboard** agent (lives under `app/`). Schema, parsers, and source files are unchanged by this design — the LLM is a read-only consumer of the same SQLite bus everyone else uses.

---

## 1. What the LLM is for (and not)

From [`../CLAUDE.md`](../CLAUDE.md) §6, restated as user-facing capabilities:

| Use the LLM for | Don't use the LLM for |
|---|---|
| Free-text Q&A across domains ("did my HDL move after I cut seed oils?") | Parsing source files (parsers own that) |
| Narrative summaries of a chart or window | Computing trends, deltas, regressions — Python/pandas/SQL |
| Explaining a derived trait in plain English | Joining tables, filtering by date |
| Suggesting follow-up questions / things to discuss with provider | Diagnosing anything. Output always ends with "discuss with provider" for medical-shaped answers |
| Composing the daily brief on Home | Dispatching between parsers or making routing decisions |

If a question reduces to a query the dashboard could compute deterministically, the dashboard computes it and **passes the answer to the LLM as context**, not the other way around.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Streamlit (app/)                                           │
│                                                             │
│   View pages ──────────┐                                    │
│                        │  "Ask about this" button           │
│                        ▼                                    │
│                ┌──────────────┐                             │
│                │  Chat panel  │  ←─── user prompt           │
│                └──────┬───────┘                             │
│                       │                                     │
└───────────────────────┼─────────────────────────────────────┘
                        │
              ┌─────────▼──────────┐
              │  app/llm/agent.py  │   tool-using loop
              │                    │
              │  - system prompt   │
              │  - tool schemas    │
              │  - convo history   │
              └─────┬─────────┬────┘
                    │         │
        ┌───────────▼─┐     ┌─▼──────────────────┐
        │ Privacy     │     │ Tool registry      │
        │ filter      │     │ (read-only views)  │
        │ (in + out)  │     └─┬──────────────────┘
        └───────┬─────┘       │
                │             ▼
                │     ┌─────────────────┐
                │     │  health.db      │
                │     │  (SQLite, RO)   │
                │     └─────────────────┘
                ▼
        ┌─────────────────┐
        │ Anthropic API   │   claude-opus-4-7 for judgment
        │ (cloud)         │   claude-haiku-4-5 for daily brief
        └─────────────────┘
```

### Layers, top to bottom

1. **Streamlit chat panel.** Renders messages, streams responses, exposes "Ask about this" affordance on each view.
2. **Agent loop (`app/llm/agent.py`).** Standard tool-use loop. System prompt + tool schemas + convo history → API call → tool calls executed locally → results fed back → final text.
3. **Privacy filter.** Wraps every call in both directions. Inputs scrubbed before egress; outputs scrubbed before display (defense in depth). See §4.
4. **Tool registry.** A small set of named, schema'd functions the LLM may call. Each one is a parameterized query against `health.db` returning aggregated/derived data only. No raw genotypes. No `private/`-sourced rows.
5. **`health.db`.** Opened read-only (`mode=ro`). The LLM cannot mutate the bus.
6. **Anthropic API.** Provider choice: this is already a Claude-Code shop; staying on Anthropic SDK keeps the surface familiar and lets us use prompt caching for the system prompt + tool schemas, which barely change.

### Why a tool-using agent rather than RAG-over-DB-dump

- RAG would require chunking and embedding the database, which means raw data leaves the host. Tool-use keeps the data local; only the **answers** to deterministic queries are sent.
- Tool-use gives us a clean privacy chokepoint: every byte the LLM sees about the user's data passes through a tool. Audit one tool, you've audited one capability.
- The dataset is small (n=1, years of daily rows) — no scale argument for vector search.

---

## 3. Tool surface

Each tool is a Python function with a JSON Schema, registered with the API. The LLM picks tools; the loop dispatches them locally; the result text is what the LLM sees.

| Tool | Purpose | Returns | Privacy notes |
|---|---|---|---|
| `list_metrics()` | What labs exist for Will | `[{metric, unit, n_observations, first_date, last_date}]` | Safe |
| `get_lab_series(metric, since?, until?)` | Time series for one lab | `[{date, value, ref_low, ref_high}]` | Safe |
| `get_lab_window_summary(metric, days)` | Min/max/mean/last over window | `{min, max, mean, last, delta_pct, in_range_pct}` | Safe |
| `get_nutrition_window(days, group_by?)` | Macros, calories, micros | `[{date, kcal, protein_g, carb_g, fat_g, ...}]` | Safe |
| `get_body_composition(since?)` | DEXA snapshots | `[{date, bf_pct, lbm_kg, vat_g, ...}]` | Safe |
| `get_lift_prs(lift?)` | Estimated 1RM trend | `[{date, lift, e1rm}]` | Safe |
| `get_sleep_window(days)` | Sleep duration + stages | `[{date, total_hr, rem_hr, deep_hr}]` | Safe |
| `get_traits(category?)` | **Derived** genome traits | `[{trait, category, value, source}]` | **Filtered:** only the `traits` table, never `snps`. Never the `pedigree` table. |
| `get_events(since, until)` | Cross-domain timeline | `[{date, domain, event_type, summary}]` | Safe; `payload_json` stripped, only `summary` exposed |
| `correlate(metric_a, metric_b, window_days)` | Pearson r + scatter pairs | `{r, n, ci, pairs}` | Computed in Python; LLM only interprets |

**Out of scope on purpose:**

- No `run_sql(query)`. Too easy to ask for `SELECT * FROM snps`.
- No `read_file(path)`. The filesystem is not the LLM's concern.
- No `get_snps(...)`. The genome agent's hardest rule per [`../CLAUDE.md`](../CLAUDE.md) §8: derived traits and summary stats only.
- No `get_pedigree(...)`. `pedigree` is sourced from `private/` (GEDCOM with living minor).

Tool calls are logged to `analysis/llm_audit.jsonl` (gitignored) with `{ts, tool, args, n_rows_returned}` so the privacy posture is auditable after the fact.

---

## 4. Privacy filter

Two-pass scrub. Both directions. Tested.

**Outbound (before each API call):**

- Strip any `rsid`-like token (`r'\brs\d{4,}\b'`).
- Strip any genotype-like pair (`r'\b[ACGT]{2}\b'` when adjacent to "rs" or "genotype" keywords).
- Strip any name from `pedigree` (loaded once at process start; the *names* never leave the process either — we just check substring).
- If the user's message contains any of the above patterns, **refuse with a fixed string** before calling the API. Don't sanitize-and-send; refuse and tell the user why.

**Inbound (before display, and before feeding into next turn):**

- Same patterns. If the model echoes one back (it shouldn't, since it never saw one), drop the message and surface an internal warning.

**Fail-loud:**

- Privacy refusal is loud, not silent. A red banner ("That request was blocked because it referenced raw genotype data; the LLM only sees derived traits.") with a link to this doc.
- Filter unit tests live in `app/llm/tests/test_privacy_filter.py` and run in CI. A schema change that adds a sensitive column should add a corresponding test.

---

## 5. Prompting

### System prompt (cached)

Roughly:

> You are a personal-health analyst for one user. You have read-only tool access to their bloodwork, nutrition, body composition, sleep, lifts, and derived genome traits.
>
> Rules: don't diagnose; end medical-shaped answers with "discuss with provider". Don't guess — call a tool. Cite specific dates and values from tool results. If a tool returns no rows, say so plainly; do not invent.
>
> You never see raw genotypes, raw rsids, or pedigree data. If the user asks for those, explain the constraint and offer a derived alternative.

Cached via Anthropic prompt caching: system prompt + tool schemas + the trait/lab catalogue (small, stable). Conversation turns are not cached.

### Per-turn context

The chat panel injects a small **context header** when the user comes in via "Ask about this" on a specific view:

```
[Context: viewing Labs > HDL, window = last 24 months]
```

This nudges the model to scope the first tool call. The user can override.

### Cite-your-sources

The agent loop appends a footer to every assistant message listing the tool calls used and the row counts. The UI renders each cited tool call as a clickable chip that opens the corresponding view filtered to those rows. This makes hallucination visible: a claim with no citation is a claim the model made up.

---

## 6. Model selection + cost

- **Daily brief on Home** — `claude-haiku-4-5` (cheap, summary-shaped). One generation per day, cached.
- **Free-text chat** — `claude-opus-4-7` for judgment-heavy questions. Switchable per-thread via a small dropdown.
- **No streaming-to-cloud of anything other than (a) the user's prompt, (b) tool results that already passed the filter, (c) the system prompt.**

The whole thing is opt-in. Missing `ANTHROPIC_API_KEY` → dashboard runs fine, "Ask" page shows a setup prompt, "Ask about this" affordances are hidden. Fail-loud at startup, per [`../CLAUDE.md`](../CLAUDE.md) §7.

---

## 7. Failure modes the design must survive

| Failure | Mitigation |
|---|---|
| API key missing or invalid | LLM features disabled cleanly; rest of dashboard works. |
| API down / rate-limited | Chat shows error inline; suggests retry. No silent fallback to a different model. |
| Model hallucinates a value | Cite-your-sources footer + clickable chips makes uncited claims obvious. User has the underlying chart in the next pane. |
| Model gives medical advice | System prompt forbids; output post-check looks for diagnostic verbs ("you have X") and appends the "discuss with provider" footer if missing. |
| User asks about pedigree / raw genome | Privacy filter refuses outbound; offers a derived alternative. |
| User asks the LLM to write a parser | LLM is in dashboard context, has no file-write tools; it can suggest text but cannot ship. |
| Tool call returns 50k rows | Tools enforce a row cap (e.g. 500) and surface a "narrow your question" hint to the model. |

---

## 8. What this does **not** include

Out of scope for v1, captured here so we don't drift:

- **No long-term memory across sessions.** Each Streamlit session starts a fresh chat. The DB is the memory.
- **No agent actions.** The LLM cannot ingest, cannot write to the DB, cannot edit files, cannot push commits. Read-only consumer.
- **No multi-user.** Single user, local, no auth. If you find yourself adding accounts, stop ([`../CLAUDE.md`](../CLAUDE.md) §3).
- **No "explain my whole genome" mode.** That would push the model toward raw-data requests. Trait-level Q&A only.

---

## 9. Implementation notes for the dashboard agent

Suggested layout under `app/`:

```
app/
├── main.py
├── views/                   # one Streamlit page per cross-domain insight
│   ├── home.py
│   ├── labs.py
│   ├── nutrition.py
│   ├── body.py
│   ├── genome.py
│   ├── timeline.py
│   ├── sources.py
│   └── ask.py               # full chat
├── llm/
│   ├── agent.py             # tool-use loop
│   ├── tools.py             # the registry from §3
│   ├── privacy.py           # the filter from §4
│   ├── prompts.py           # system prompt + per-view context headers
│   └── tests/
│       ├── test_privacy_filter.py
│       └── test_tools_no_raw_genome.py
└── db.py                    # opens analysis/health.db read-only
```

A first slice that delivers value: home daily brief + the Ask page + `get_lab_series` + `get_lab_window_summary` + privacy filter. Everything else is incremental — add tools as Will reaches for questions the agent can't answer.
