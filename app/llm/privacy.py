"""
privacy.py — outbound + inbound filter per docs/LLM_INTERFACE.md §4.

Defense in depth:
- Outbound: scrub before egress. If the user's message contains raw rsids
  or genotype patterns, REFUSE LOUDLY (don't sanitize-and-send).
- Inbound: same patterns. If the model echoes one back, drop the message
  and surface an internal warning.

Wargame mitigations:
- W1 (Mattie's GEDCOM): pedigree names are loaded once at process start
  and any substring match in user input refuses.
- W2 (paste raw rsids): rsid regex covers common mangling variants.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# rs-ID variants. False positives are fine; false negatives are not.
#   rs12345        - canonical
#   RS12345        - upper
#   r_s12345       - underscore
#   rs 12345       - space
#   rs-12345       - dash
RSID_RE = re.compile(r"\b(?:rs|RS|Rs|r_s|R_S)[\s_\-]*\d{3,}\b")

# Genotype pair near an rs/genotype keyword. "AA", "AT", "GC", etc.
# Two-pass: simple ACGT-pair when it appears in close proximity to "rs"/"genotype".
GENOTYPE_NEAR_RSID_RE = re.compile(
    r"(?i)\b(?:rs|RS|r_s|genotype)\S*\s*[:=]?\s*[ACGTacgt]{2}\b"
)
# Also catch a standalone "AA"/"AT" line in a paste like `rs4988235 GG`
LOOSE_GENOTYPE_LINE_RE = re.compile(r"(?im)^\s*rs\S*\s+[ACGTacgt]{2}\s*$")


@dataclass(frozen=True)
class FilterResult:
    """Outcome of running the filter on a text. `ok` means safe to send."""

    ok: bool
    reason: str = ""
    matches: tuple[str, ...] = ()


class PrivacyFilter:
    """Stateful filter. Holds the (lower-cased) set of pedigree names so
    repeated calls don't reload them from disk.

    `pedigree_names` is intentionally NOT exposed via any tool — names live
    only in this process and are matched as substrings.
    """

    def __init__(self, pedigree_names: Optional[Iterable[str]] = None):
        self._names = tuple(
            n.strip().lower()
            for n in (pedigree_names or ())
            if n and len(n.strip()) >= 3  # avoid matching 'Bo' etc.
        )

    @classmethod
    def from_default(cls) -> "PrivacyFilter":
        """Load pedigree names from `private/` if present, else empty.

        We never write the names back to disk and never include them in
        any response or tool result.
        """
        names: list[str] = []
        # Try a few common locations without crashing if they don't exist.
        root = Path(__file__).parent.parent.parent
        ged = root / "private" / "craig_gedcom" / "Craig Family Tree.ged"
        if ged.exists():
            try:
                with open(ged, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        # GEDCOM NAME lines look like "1 NAME John /Smith/"
                        if " NAME " in line:
                            raw = line.split(" NAME ", 1)[1].strip()
                            # Strip slashes used to mark surnames
                            cleaned = raw.replace("/", " ").strip()
                            for tok in cleaned.split():
                                if len(tok) >= 3 and tok.isalpha():
                                    names.append(tok)
            except OSError:
                pass
        return cls(names)

    def check(self, text: str) -> FilterResult:
        """Returns FilterResult. ok=False means refuse."""
        if not text:
            return FilterResult(ok=True)
        matches: list[str] = []

        # 1) rsid patterns
        for m in RSID_RE.findall(text):
            matches.append(m)

        # 2) genotype-near-rs patterns
        for m in GENOTYPE_NEAR_RSID_RE.findall(text):
            matches.append(m)
        for m in LOOSE_GENOTYPE_LINE_RE.findall(text):
            matches.append(m)

        # 3) pedigree-name substring match (case-insensitive)
        if self._names:
            t_lower = text.lower()
            for name in self._names:
                # word-boundary-ish match: require non-letter on either side
                idx = t_lower.find(name)
                while idx >= 0:
                    before = t_lower[idx - 1] if idx > 0 else " "
                    after_i = idx + len(name)
                    after = t_lower[after_i] if after_i < len(t_lower) else " "
                    if not before.isalpha() and not after.isalpha():
                        matches.append(name)
                        break
                    idx = t_lower.find(name, idx + 1)

        if matches:
            return FilterResult(
                ok=False,
                reason=(
                    "Blocked: that referenced raw genotype or pedigree data. "
                    "The LLM only sees derived traits. Ask about the *trait* "
                    "(e.g. 'what does my methylation trait look like?')."
                ),
                matches=tuple(dict.fromkeys(matches)),  # de-dupe, preserve order
            )
        return FilterResult(ok=True)


def screen_diagnostic_verbs(text: str) -> bool:
    """Wargame W4: post-check for diagnostic verbs.

    Returns True if any verbatim diagnostic-flavored phrase is found.
    Caller decides whether to append a 'discuss with provider' footer.
    """
    if not text:
        return False
    patterns = [
        r"\byou have (?:a|an)? ?[A-Za-z]+\b",
        r"\bthis is (?:a|an)? ?[A-Za-z]+ ?(?:disease|disorder|syndrome|condition)\b",
        r"\byou (?:are|seem|appear) diagnos\w*\b",
        r"\b(?:diagnosis|diagnosed)\s+with\b",
    ]
    for p in patterns:
        if re.search(p, text, flags=re.IGNORECASE):
            return True
    return False
