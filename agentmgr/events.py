"""The event log: one immutable JSON file per event in ``.agentmgr/events/``.

Filenames are ``<ulid>-<actor>.json``. Because the ULID is unique, two actors
never write the same path, so there is no locking and no write race. The file
is created with exclusive mode (``"x"``) so an accidental id collision fails
loudly instead of clobbering.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agentmgr.paths import Layout
from agentmgr.ulid import new_ulid

_ACTOR_RE = re.compile(r"[^a-zA-Z0-9._-]+")
_TS_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"

KNOWN_EVENTS: frozenset[str] = frozenset(
    {
        "agent-join",
        "claim-solo",
        "charter-ack",
        "manager-active",
        "manager-idle",
        "thread-open",
        "thread-claim",
        "thread-update",
        "thread-close",
        "handoff-created",
        "handoff-accepted",
        "decision-proposed",
        "decision-ratified",
        "check-run",
        "heartbeat",
    }
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime(_TS_FMT)


def parse_iso(ts: str) -> datetime:
    return datetime.strptime(ts, _TS_FMT).replace(tzinfo=timezone.utc)


def sanitise_actor(actor: str) -> str:
    cleaned = _ACTOR_RE.sub("-", actor.strip()).strip("-")
    if not cleaned:
        raise ValueError(f"actor id {actor!r} has no usable characters")
    return cleaned


@dataclass(frozen=True)
class Event:
    id: str
    ts: str
    actor: str
    event: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "actor": self.actor,
            "event": self.event,
            "data": dict(self.data),
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Event":
        return Event(
            id=raw["id"],
            ts=raw["ts"],
            actor=raw["actor"],
            event=raw["event"],
            data=raw.get("data") or {},
        )


def append_event(
    layout: Layout,
    event: str,
    actor: str,
    data: dict[str, Any] | None = None,
) -> Event:
    actor = sanitise_actor(actor)
    layout.events.mkdir(parents=True, exist_ok=True)
    ev = Event(id=new_ulid(), ts=now_iso(), actor=actor, event=event, data=data or {})
    path = layout.events / f"{ev.id}-{actor}.json"
    body = json.dumps(ev.to_dict(), indent=2, sort_keys=True, ensure_ascii=False)
    with open(path, "x", encoding="utf-8") as fh:  # exclusive create
        fh.write(body + "\n")
    return ev


def read_events(layout: Layout) -> list[Event]:
    if not layout.events.is_dir():
        return []
    events: list[Event] = []
    for path in sorted(layout.events.glob("*.json")):
        try:
            events.append(Event.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, KeyError) as exc:
            raise ValueError(f"corrupt event file {path.name}: {exc}") from exc
    events.sort(key=lambda e: e.id)
    return events
