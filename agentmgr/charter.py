"""Read the Charter's declared version and content hash, and record decisions in it.

``charter-ack`` events carry ``{"version": N, "sha256": "..."}`` so other actors
can see at a glance whether an agent has read the *current* Charter.

``record_decision`` turns a ratified decision into an ADR draft at the end of
the Charter and bumps its version, which is what the Charter's own header asks
for ("kabul edilirse sürüm numarasını artır").
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

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


_ADR_RE = re.compile(r"^### ADR-(\d+):[ \t]*(.*)$", re.MULTILINE)
_UPDATED_RE = re.compile(r"(\*\*Son g[uü]ncelleme:\*\*)[^\n]*", re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(r"^_<[^<>]*>_$")


@dataclass(frozen=True)
class AdrResult:
    """What ``record_decision`` did. ``adr`` is None when nothing was written."""

    adr: str | None
    version_before: int | None
    version_after: int | None
    skipped: str | None = None


def _indent_continuation(text: str) -> str:
    lines = text.strip().splitlines() or [""]
    return "\n".join([lines[0]] + ["  " + line for line in lines[1:]])


def _adr_entry(number: int, decision_id: str, title: str, body: str, ratifier: str, today: str) -> str:
    context = _indent_continuation(body) if body.strip() else "_<neden bir karara ihtiyaç vardı>_"
    return (
        f"### ADR-{number:03d}: {title.strip()}\n"
        f"\n"
        f"- **Tarih:** {today}\n"
        f"- **Durum:** kabul edildi (`decision ratify {decision_id}`, {ratifier})\n"
        f"- **Bağlam:** {context}\n"
        f"- **Karar:** {title.strip()}\n"
        f"- **Sonuç:** _<etkileri ve ödünleşimleri yaz>_\n"
    )


def record_decision(
    layout: Layout,
    decision_id: str,
    title: str,
    body: str,
    ratifier: str,
    today: str,
) -> AdrResult | None:
    """Append an ADR draft for a ratified decision and bump the Charter version.

    Returns ``None`` when there is no Charter. If the Charter already mentions
    ``decision_id`` nothing is written. A still-unfilled template ADR
    (``### ADR-001: _<başlık>_``) is replaced rather than left dangling.
    """
    if not layout.charter.exists():
        return None
    raw = layout.charter.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")

    match = _VERSION_RE.search(text)
    before = int(match.group(1)) if match else None
    if re.search(r"(?<![\w-])" + re.escape(decision_id) + r"(?![\w-])", text):
        return AdrResult(None, before, before, skipped="CHARTER.md already mentions this decision")

    heads = list(_ADR_RE.finditer(text))
    template = next((h for h in heads if _PLACEHOLDER_RE.match(h.group(2).strip())), None)
    if template is not None:
        number = int(template.group(1))
        later = [h.start() for h in heads if h.start() > template.start()]
        end = later[0] if later else len(text)
        entry = _adr_entry(number, decision_id, title, body, ratifier, today)
        text = text[: template.start()] + entry + ("\n" + text[end:] if later else "")
    else:
        number = max((int(h.group(1)) for h in heads), default=0) + 1
        entry = _adr_entry(number, decision_id, title, body, ratifier, today)
        text = text.rstrip("\n") + "\n\n" + entry

    after = before
    match = _VERSION_RE.search(text)
    if match:
        after = int(match.group(1)) + 1
        text = text[: match.start(1)] + str(after) + text[match.end(1) :]
    text = _UPDATED_RE.sub(lambda m: f"{m.group(1)} _{today}_", text, count=1)

    layout.charter.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return AdrResult(f"ADR-{number:03d}", before, after)
