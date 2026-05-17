# docs/ — Index

- [VISION.md](VISION.md) — *(architect, 2026-05-16)* distinctive angle, competitive scan, proposed additions (risk agent, calculators plugin, narrative view)
- [ORCHESTRATION.md](ORCHESTRATION.md) — agent domains, software structure, critical path
- [WORKFLOW.md](WORKFLOW.md) — git policy: branch per agent, push always, never auto-merge master, post-rewrite reset protocol
- [SCHEMA.md](SCHEMA.md) — *(written by Schema agent)* table contracts every other agent reads
- [CROSS_AGENT_NOTES.md](CROSS_AGENT_NOTES.md) — *(append-only)* out-of-lane observations agents make about other domains
- [LLM_INTERFACE.md](LLM_INTERFACE.md) — Claude integration in the dashboard: tool surface, privacy filter, prompt strategy
- [UI_STRUCTURE.md](UI_STRUCTURE.md) — Streamlit layout (left rail / main / chat rail), pages, components
- [USER_FLOW.md](USER_FLOW.md) — happy-path session walkthrough + 11 wargamed adversarial scenarios
- [SYNTHESIS.md](SYNTHESIS.md) — *the why layer above UI/LLM:* 8 cross-data synthesis principles + 7 reusable analytical patterns + anti-patterns + code map

Root-level references:
- [`CLAUDE.md`](../CLAUDE.md) — cross-cutting behavioral rules every agent inherits
- [`AGENTS.md`](../AGENTS.md) — registry every agent reads on startup

**Doc placement rule:** new docs default to `docs/`. Only files that must be at root for tooling or protocol reasons stay there: `CLAUDE.md` (auto-loaded), `AGENTS.md` (cross-branch registry), `README.md` (convention).
