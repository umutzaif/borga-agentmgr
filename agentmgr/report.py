"""Shared coordination checks used by ``reconcile`` and ``manager run``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agentmgr.events import parse_iso
from agentmgr.state import (
    DEFAULT_MANAGER_STALE_MINUTES,
    DEFAULT_STALE_MINUTES,
    DEFAULT_THREAD_STALE_MINUTES,
    ProjectState,
)


def findings(
    state: ProjectState,
    solo_stale_minutes: int = DEFAULT_STALE_MINUTES,
    thread_stale_minutes: int | None = None,
    manager_stale_minutes: int | None = None,
    charter_sha: str | None = None,
    now: datetime | None = None,
) -> list[str]:
    if thread_stale_minutes is None:
        thread_stale_minutes = DEFAULT_THREAD_STALE_MINUTES
    if manager_stale_minutes is None:
        manager_stale_minutes = DEFAULT_MANAGER_STALE_MINUTES
    now = now or datetime.now(timezone.utc)
    out: list[str] = []

    # a stale `manager run` leaves everyone else stuck in MANAGED mode
    if state.manager:
        mgr = state.agents.get(state.manager)
        if mgr and parse_iso(mgr.last_seen) < now - timedelta(minutes=manager_stale_minutes):
            out.append(
                f"stale manager: {state.manager} - no event since {mgr.last_seen}; "
                f"MANAGED mode may be stuck (run 'agentmgr manager start --as <id>' to take over)"
            )

    for actor in sorted(state.stale_agents(solo_stale_minutes, now)):
        seen = state.agents[actor].last_seen
        out.append(f"orphaned solo claim: {actor} silent > {solo_stale_minutes}m (last {seen})")

    for ag in sorted(state.agents.values(), key=lambda a: a.actor):
        owns = any(t.owner == ag.actor for t in state.threads.values())
        if ag.charter_ack is None and (ag.solo or owns):
            out.append(f"no charter-ack on record for active agent {ag.actor}")
        if charter_sha and ag.charter_sha and ag.charter_sha != charter_sha:
            out.append(
                f"charter drift: {ag.actor} acked {ag.charter_sha[:8]} "
                f"but CHARTER.md is now {charter_sha[:8]}"
            )

    thread_cutoff = now - timedelta(minutes=thread_stale_minutes)
    for thread in sorted(state.open_threads(), key=lambda t: t.id):
        if thread.updated and parse_iso(thread.updated) < thread_cutoff:
            out.append(
                f"stale thread {thread.id} ({thread.status}) - no update since {thread.updated}"
            )

    if state.mode == "CONTESTED":
        out.append("mode CONTESTED: multiple solo claims and no active manager")

    return out
