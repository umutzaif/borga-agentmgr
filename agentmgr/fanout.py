"""Capability-aware thread assignment for TEAM mode.

A thread carries ``tags``; an agent carries ``strengths`` (from its
``agent-join`` event). ``plan_auto_assign`` matches unowned open threads to
joined agents by tag overlap, breaking ties by current load.
"""

from __future__ import annotations

from agentmgr.state import ProjectState


def candidate_agents(state: ProjectState) -> list[str]:
    """Agents eligible to own threads: they joined explicitly and aren't the manager."""
    return sorted(
        a.actor
        for a in state.agents.values()
        if a.joined_explicitly and a.actor != state.manager
    )


def score(thread_tags: list[str], agent_strengths: list[str]) -> int:
    return len(set(thread_tags) & set(agent_strengths))


def plan_auto_assign(state: ProjectState) -> list[tuple[str, str, str]]:
    """[(thread_id, agent, reason)] for every unowned open thread."""
    agents = candidate_agents(state)
    if not agents:
        return []

    load = {a: 0 for a in agents}
    for t in state.open_threads():
        if t.owner in load:
            load[t.owner] += 1

    plan: list[tuple[str, str, str]] = []
    for thread in sorted((t for t in state.open_threads() if not t.owner), key=lambda x: x.id):
        ranked = sorted(
            agents,
            key=lambda a: (-score(thread.tags, state.agents[a].strengths), load[a], a),
        )
        best = ranked[0]
        overlap = sorted(set(thread.tags) & set(state.agents[best].strengths))
        reason = f"tags {overlap}" if overlap else "no tag match - least loaded"
        plan.append((thread.id, best, reason))
        load[best] += 1
    return plan
