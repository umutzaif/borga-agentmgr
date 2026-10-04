"""Capability-aware thread assignment for TEAM mode.

A thread carries ``tags``; an agent carries ``strengths`` (from its
``agent-join`` event). ``plan_auto_assign`` matches unowned open threads to
joined agents by tag overlap, breaking ties by current load. The active
manager is skipped by default, but is eligible for a thread it matches by tag.
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
    manager = state.manager if state.manager in state.agents else None
    manager_joined = bool(manager and state.agents[manager].joined_explicitly)
    if not agents and not manager_joined:
        return []

    load = {a: 0 for a in agents + ([manager] if manager_joined else [])}
    for t in state.open_threads():
        if t.owner in load:
            load[t.owner] += 1

    plan: list[tuple[str, str, str]] = []
    for thread in sorted((t for t in state.open_threads() if not t.owner), key=lambda x: x.id):
        pool = list(agents)
        if manager_joined and score(thread.tags, state.agents[manager].strengths) > 0:
            pool.append(manager)
        if not pool:
            continue
        ranked = sorted(
            pool,
            key=lambda a: (-score(thread.tags, state.agents[a].strengths), load[a], a),
        )
        best = ranked[0]
        overlap = sorted(set(thread.tags) & set(state.agents[best].strengths))
        reason = f"tags {overlap}" if overlap else "no tag match - least loaded"
        if best == manager:
            reason += " (manager works too)"
        plan.append((thread.id, best, reason))
        load[best] += 1
    return plan
