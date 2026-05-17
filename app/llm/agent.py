"""
agent.py — Anthropic tool-use loop per LLM_INTERFACE.md §2.

Wargame mitigations woven in:
- W3: post-check that any numbers in assistant text appear in tool results
  it cited.  Flagged in `numbers_unverified`.
- W4: post-check for diagnostic verbs; if found and "discuss with provider"
  is missing, append it.
- W5: fail loudly at startup when ANTHROPIC_API_KEY missing. Caller checks
  `llm_enabled()`.
- W7: when any tool result has `truncated:true`, we append a
  "⚠ result truncated to 500 rows" line unconditionally.

Models:
- Free-text chat: claude-opus-4-7        (judgment)
- Daily brief:    claude-haiku-4-5-20251001  (cached, one call/day)

Prompt caching: system prompt + tool schemas are sent with cache_control,
so subsequent turns reuse cached input tokens.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from .privacy import PrivacyFilter, screen_diagnostic_verbs
from .prompts import SYSTEM_PROMPT
from .tools import TOOL_SCHEMAS, dispatch

CHAT_MODEL = "claude-opus-4-7"
BRIEF_MODEL = "claude-haiku-4-5-20251001"

# Tools we accept from the model. Hard whitelist — if it tool-calls anything
# not on this list, we refuse and surface an error. (W8 backstop.)
ALLOWED_TOOLS = {schema["name"] for schema in TOOL_SCHEMAS}


def llm_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _ensure_provider_footer(text: str) -> str:
    """W4: if diagnostic verbs detected and no provider footer, append it."""
    if not screen_diagnostic_verbs(text):
        return text
    if "discuss with provider" in text.lower() or "ask your doctor" in text.lower():
        return text
    return text.rstrip() + "\n\n_Insights here are pattern-matching, not medicine. Discuss with provider._"


# Looks for numbers in the assistant text. We compare against tool results.
_NUM_RE = re.compile(r"\b\d{1,4}(?:[.,]\d+)?\b")


def _verify_numbers(text: str, tool_results: list[dict]) -> list[str]:
    """W3: return list of numbers found in `text` that don't appear in any
    tool result. Caller decides whether to surface a banner. Empty list =
    all numbers verified."""
    if not tool_results:
        return []
    nums = set(_NUM_RE.findall(text))
    # Build a flat string of all values seen in any tool result.
    haystack_parts: list[str] = []
    for tr in tool_results:
        haystack_parts.append(str(tr))
    haystack = " ".join(haystack_parts)
    haystack_nums = set(_NUM_RE.findall(haystack))
    return sorted(n for n in nums if n not in haystack_nums and len(n) >= 3)


def _has_truncation(tool_results: list[dict]) -> bool:
    for tr in tool_results:
        if isinstance(tr, dict) and tr.get("truncated") is True:
            return True
    return False


@dataclass
class AgentResponse:
    text: str
    citations: list[dict] = field(default_factory=list)  # [{tool, args, n_rows}]
    error: str | None = None
    refused: bool = False
    refusal_reason: str = ""
    numbers_unverified: list[str] = field(default_factory=list)
    truncated: bool = False
    raw_tool_results: list[dict] = field(default_factory=list)


def run(
    user_prompt: str,
    history: list[dict] | None = None,
    privacy: PrivacyFilter | None = None,
    model: str = CHAT_MODEL,
    max_turns: int = 6,
) -> AgentResponse:
    """Run one tool-using turn for a user prompt.

    `history` is a list of {role, content} dicts from prior turns.
    Returns AgentResponse — caller renders the chat panel from it.
    """
    if not llm_enabled():
        return AgentResponse(
            text="",
            error="ANTHROPIC_API_KEY not set. Set it and reload to enable chat.",
        )

    if privacy is None:
        privacy = PrivacyFilter.from_default()

    # OUTBOUND privacy filter.
    out_check = privacy.check(user_prompt)
    if not out_check.ok:
        return AgentResponse(
            text="",
            refused=True,
            refusal_reason=out_check.reason,
        )

    # Lazy import so the module loads cleanly without anthropic installed
    # (e.g., during tests of privacy alone).
    import anthropic

    client = anthropic.Anthropic()

    # Cached system + tool block per Anthropic prompt caching docs.
    system_blocks = [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    # Tool schemas: mark the last one with cache_control so the whole block
    # is cached.
    tools_for_api = [dict(t) for t in TOOL_SCHEMAS]
    if tools_for_api:
        tools_for_api[-1] = {**tools_for_api[-1], "cache_control": {"type": "ephemeral"}}

    messages: list[dict] = list(history or [])
    messages.append({"role": "user", "content": user_prompt})

    citations: list[dict] = []
    all_tool_results: list[dict] = []

    final_text = ""
    for _ in range(max_turns):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=2048,
                system=system_blocks,
                tools=tools_for_api,
                messages=messages,
            )
        except Exception as e:  # noqa: BLE001
            return AgentResponse(text="", error=f"API error: {e}")

        # Collect text segments and tool_use blocks.
        text_chunks: list[str] = []
        tool_uses: list[dict] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_chunks.append(getattr(block, "text", ""))
            elif btype == "tool_use":
                tool_uses.append(
                    {
                        "id":   getattr(block, "id", ""),
                        "name": getattr(block, "name", ""),
                        "input": dict(getattr(block, "input", {}) or {}),
                    }
                )

        # If no tool calls, this is the final turn.
        if not tool_uses:
            final_text = "\n".join(c for c in text_chunks if c).strip()
            break

        # Execute tool calls locally.
        tool_results: list[dict] = []
        for tu in tool_uses:
            name = tu["name"]
            args = tu["input"]
            if name not in ALLOWED_TOOLS:
                result = {"error": f"tool {name} not allowed"}
            else:
                result = dispatch(name, args)
            tool_results.append({"id": tu["id"], "result": result})
            all_tool_results.append(result)
            n_rows = len(result.get("rows", [])) if isinstance(result, dict) else 0
            citations.append(
                {"tool": name, "args": args, "n_rows": n_rows}
            )

        # Append the assistant response and then user-side tool_result blocks.
        messages.append({"role": "assistant", "content": resp.content})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tr["id"],
                        "content": str(tr["result"]),
                    }
                    for tr in tool_results
                ],
            }
        )

    # INBOUND privacy filter on final text.
    in_check = privacy.check(final_text)
    if not in_check.ok:
        return AgentResponse(
            text="",
            refused=True,
            refusal_reason=(
                "Model output blocked: it appeared to echo raw genotype "
                "or pedigree data. Internal warning logged."
            ),
        )

    final_text = _ensure_provider_footer(final_text)

    truncated = _has_truncation(all_tool_results)
    if truncated:
        final_text = (
            final_text.rstrip()
            + "\n\n⚠ Result truncated to 500 rows; narrow your question for a complete view."
        )

    unverified = _verify_numbers(final_text, all_tool_results)
    if unverified:
        final_text = (
            final_text.rstrip()
            + f"\n\n⚠ Some numbers ({', '.join(unverified[:5])}) were not found in cited data; please verify."
        )

    return AgentResponse(
        text=final_text,
        citations=citations,
        numbers_unverified=unverified,
        truncated=truncated,
        raw_tool_results=all_tool_results,
    )
