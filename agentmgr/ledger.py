"""Derived, hash-chained mirror of ``events/`` written to ``ledger.jsonl``.

The ledger is a cache: it can be deleted and rebuilt from ``events/`` at any
time. Each row carries ``seq`` (1-based), ``prev`` (hash of the previous row)
and ``hash`` (sha256 of this row without the ``hash`` field). That chain lets a
reproducibility auditor confirm nothing was inserted, dropped, or edited.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from agentmgr.events import Event, read_events
from agentmgr.paths import Layout

GENESIS = "0" * 64


def _canonical(obj: dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_row(row_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(row_without_hash).encode("utf-8")).hexdigest()


def chain(events: list[Event]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prev = GENESIS
    for seq, ev in enumerate(events, start=1):
        row = ev.to_dict()
        row["seq"] = seq
        row["prev"] = prev
        row["hash"] = _hash_row(row)
        prev = row["hash"]
        rows.append(row)
    return rows


def rebuild(layout: Layout) -> list[dict[str, Any]]:
    rows = chain(read_events(layout))
    layout.ledger.parent.mkdir(parents=True, exist_ok=True)
    # write to a temp file then atomically swap, so a concurrent reader never
    # sees a half-written ledger
    tmp = layout.ledger.with_suffix(layout.ledger.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(_canonical(row) + "\n")
    os.replace(tmp, layout.ledger)
    return rows


def head(layout: Layout) -> str:
    rows = chain(read_events(layout))
    return rows[-1]["hash"] if rows else GENESIS


def verify(layout: Layout) -> tuple[bool, str]:
    """Check the on-disk ledger for internal consistency and agreement with events."""
    if not layout.ledger.exists():
        return False, "ledger.jsonl missing - run 'agentmgr status' to rebuild it"

    lines = [ln for ln in layout.ledger.read_text(encoding="utf-8").splitlines() if ln.strip()]
    disk_rows = [json.loads(ln) for ln in lines]

    prev = GENESIS
    for row in disk_rows:
        stated = row.get("hash")
        body = {k: v for k, v in row.items() if k != "hash"}
        if row.get("prev") != prev:
            return False, f"broken prev link at seq {row.get('seq')}"
        if stated != _hash_row(body):
            return False, f"row hash does not match contents at seq {row.get('seq')}"
        prev = stated

    expected = chain(read_events(layout))
    if len(expected) != len(disk_rows):
        return False, (
            f"ledger has {len(disk_rows)} rows but events/ produces {len(expected)}"
        )
    for want, got in zip(expected, disk_rows):
        if want["hash"] != got.get("hash"):
            return False, f"ledger diverges from events/ at seq {want['seq']}"

    tail = disk_rows[-1]["hash"][:12] if disk_rows else "(empty)"
    return True, f"{len(disk_rows)} events, chain intact, head {tail}"
