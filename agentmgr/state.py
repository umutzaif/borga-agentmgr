"""Fold the event log into a snapshot of the project: mode, agents, threads."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from agentmgr.events import Event, parse_iso
from agentmgr.paths import Layout

DEFAULT_STALE_MINUTES = 90


@dataclass
class AgentState:
    actor: str
    joined: str
    last_seen: str
    charter_ack: int | None = None
    solo: bool = False


@dataclass
class ThreadState:
    id: str
    title: str
    status: str = "open"  # open | blocked | done
    owner: str | None = None
    next_step: str = ""
    updated: str = ""


@dataclass
class ProjectState:
    mode: str = "IDLE"
    manager: str | None = None
    manager_since: str | None = None
    agents: dict[str, AgentState] = field(default_factory=dict)
    threads: dict[str, ThreadState] = field(default_factory=dict)
    pending_handoffs: list[dict[str, Any]] = field(default_factory=list)
    event_count: int = 0
    last_event_ts: str | None = None

    def open_threads(self) -> list[ThreadState]:
        return [t for t in self.threads.values() if t.status != "done"]

    def stale_agents(self, stale_minutes: int, now: datetime | None = None) -> set[str]:
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=stale_minutes)
        return {
            a.actor
            for a in self.agents.values()
            if a.solo and parse_iso(a.last_seen) < cutoff
        }


def _touch(state: ProjectState, ev: Event) -> AgentState:
    ag = state.agents.get(ev.actor)
    if ag is None:
        ag = AgentState(actor=ev.actor, joined=ev.ts, last_seen=ev.ts)
        state.agents[ev.actor] = ag
    ag.last_seen = ev.ts
    return ag


def reconcile(events: list[Event]) -> ProjectState:
    st = ProjectState()
    for ev in events:
        st.event_count += 1
        st.last_event_ts = ev.ts
        ag = _touch(st, ev)
        data = ev.data

        if ev.event == "charter-ack":
            ag.charter_ack = data.get("version")
        elif ev.event == "claim-solo":
            ag.solo = True
        elif ev.event == "manager-active":
            st.manager = ev.actor
            st.manager_since = ev.ts
        elif ev.event == "manager-idle":
            if st.manager == ev.actor:
                st.manager = None
                st.manager_since = None
        elif ev.event == "thread-open":
            tid = data.get("id") or ev.id
            st.threads[tid] = ThreadState(
                id=tid,
                title=data.get("title", tid),
                status=data.get("status", "open"),
                owner=data.get("owner"),
                next_step=data.get("next_step", ""),
                updated=ev.ts,
            )
        elif ev.event in ("thread-update", "thread-claim"):
            thread = st.threads.get(str(data.get("id", "")))
            if thread is not None:
                if "status" in data:
                    thread.status = data["status"]
                if "next_step" in data:
                    thread.next_step = data["next_step"]
                if ev.event == "thread-claim" or "owner" in data:
                    thread.owner = data.get("owner", ev.actor)
                thread.updated = ev.ts
        elif ev.event == "thread-close":
            thread = st.threads.get(str(data.get("id", "")))
            if thread is not None:
                thread.status = "done"
                thread.updated = ev.ts
        elif ev.event == "handoff-created":
            st.pending_handoffs.append(
                {
                    "id": data.get("id"),
                    "from": data.get("from"),
                    "to": data.get("to"),
                    "ts": ev.ts,
                }
            )
        elif ev.event == "handoff-accepted":
            hid = data.get("id")
            st.pending_handoffs = [h for h in st.pending_handoffs if h.get("id") != hid]
            for other in st.agents.values():
                other.solo = False
            taker = st.agents.get(data.get("to") or ev.actor)
            if taker is not None:
                taker.solo = True

    st.mode = _derive_mode(st)
    return st


def _derive_mode(st: ProjectState) -> str:
    solo = [a.actor for a in st.agents.values() if a.solo]
    if st.manager:
        owners = {t.owner for t in st.open_threads() if t.owner}
        return "TEAM" if len(owners) > 1 else "MANAGED"
    if len(solo) == 1:
        return f"SOLO({solo[0]})"
    if len(solo) > 1:
        return "CONTESTED"  # >1 solo claim and no manager - needs a human
    return "IDLE"


def load_config(layout: Layout) -> dict[str, Any]:
    if layout.config.exists():
        try:
            return json.loads(layout.config.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"heartbeat_stale_minutes": DEFAULT_STALE_MINUTES}
