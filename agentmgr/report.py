"""Shared coordination checks used by ``reconcile`` and ``manager run``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agentmgr.events import parse_iso
from agentmgr.state import ProjectState


def findings(
    state: ProjectState,
    threshold_minutes: int,
    now: datetime | None = None,
) -> list[str]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=threshold_minutes)
    out: list[str] = []

    for actor in sorted(state.stale_agents(threshold_minutes, now)):
        seen = state.agents[actor].last_seen
        out.append(f"orphaned solo claim: {actor} silent > {threshold_minutes}m (last {seen})")

    for ag in sorted(state.agents.values(), key=lambda a: a.actor):
        owns = any(t.owner == ag.actor for t in state.threads.values())
        if ag.charter_ack is None and (ag.solo or owns):
            out.append(f"no charter-ack on record for active agent {ag.actor}")

    for thread in sorted(state.open_threads(), key=lambda t: t.id):
        if thread.updated and parse_iso(thread.updated) < cutoff:
            out.append(
                f"stale thread {thread.id} ({thread.status}) - no update since {thread.updated}"
            )

    if state.mode == "CONTESTED":
        out.append("mode CONTESTED: multiple solo claims and no active manager")

    return out
