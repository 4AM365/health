"""Date parsing helpers shared across ingest agents."""
from __future__ import annotations

import re
from datetime import datetime


_MDY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$")
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def to_iso(raw: str) -> str | None:
    """Convert M/D/Y or YYYY-MM-DD strings to ISO `YYYY-MM-DD`. Returns None if unparseable."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    m = _ISO.match(s)
    if m:
        return s

    m = _MDY.match(s)
    if m:
        mo, d, y = m.groups()
        if len(y) == 2:
            # naive 2-digit year: 70-99 -> 19xx, else 20xx
            yi = int(y)
            y = str(2000 + yi if yi < 70 else 1900 + yi)
        try:
            return datetime(int(y), int(mo), int(d)).date().isoformat()
        except ValueError:
            return None

    # last-ditch: try a few formats
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d-%b-%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None
