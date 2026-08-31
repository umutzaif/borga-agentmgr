"""Read the Charter's declared version and content hash.

``charter-ack`` events carry ``{"version": N, "sha256": "..."}`` so other actors
can see at a glance whether an agent has read the *current* Charter.
"""

from __future__ import annotations

import hashlib
import re

from agentmgr.paths import Layout

# matches '**Sürüm:** 3', '**Surum:** 3', '**Version:** 3' (optionally in a table row)
_VERSION_RE = re.compile(
    r"\*\*\s*(?:S[uü]r[uü]m|Version)\s*:\s*\*\*\s*_*\s*(\d+)",
    re.IGNORECASE,
)


def charter_fingerprint(layout: Layout) -> tuple[int | None, str | None]:
    if not layout.charter.exists():
        return None, None
    text = layout.charter.read_text(encoding="utf-8")
    match = _VERSION_RE.search(text)
    version = int(match.group(1)) if match else None
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return version, digest
