from __future__ import annotations

import unittest

from agentmgr.events import Event
from agentmgr.fanout import candidate_agents, plan_auto_assign, score
from agentmgr.state import reconcile


def ev(i, event, actor, data=None):
    return Event(id=f"U{i:04d}", ts="2026-09-01T10:00:00.000000Z", actor=actor, event=event, data=data or {})


def build(*specs):
    return reconcile([ev(i, *s) for i, s in enumerate(specs)])


class FanoutTests(unittest.TestCase):
    def test_score_counts_tag_overlap(self):
        self.assertEqual(score(["parser", "tests"], ["tests", "docs"]), 1)
        self.assertEqual(score(["a"], ["b"]), 0)

    def test_candidates_exclude_manager_and_non_joiners(self):
        st = build(
            ("agent-join", "claude-01", {"strengths": ["parser"]}),
            ("agent-join", "gpt-01", {"strengths": ["tests"]}),
            ("manager-active", "mgr", None),
            ("claim-solo", "ghost", None),  # never joined
        )
        self.assertEqual(candidate_agents(st), ["claude-01", "gpt-01"])

    def test_auto_assign_prefers_tag_match(self):
        st = build(
            ("agent-join", "claude-01", {"strengths": ["architecture", "parser"]}),
            ("agent-join", "gpt-01", {"strengths": ["tests", "speed"]}),
            ("manager-active", "mgr", None),
            ("thread-open", "mgr", {"id": "T1", "title": "Parser", "tags": ["parser"]}),
            ("thread-open", "mgr", {"id": "T2", "title": "Test suite", "tags": ["tests"]}),
        )
        plan = dict((tid, agent) for tid, agent, _ in plan_auto_assign(st))
        self.assertEqual(plan["T1"], "claude-01")
        self.assertEqual(plan["T2"], "gpt-01")

    def test_auto_assign_load_balances_when_no_tag_match(self):
        st = build(
            ("agent-join", "a", {"strengths": []}),
            ("agent-join", "b", {"strengths": []}),
            ("manager-active", "mgr", None),
            ("thread-open", "mgr", {"id": "T1", "title": "one"}),
            ("thread-open", "mgr", {"id": "T2", "title": "two"}),
        )
        assigned = sorted(agent for _, agent, _ in plan_auto_assign(st))
        self.assertEqual(assigned, ["a", "b"])  # one each

    def test_auto_assign_skips_already_owned(self):
        st = build(
            ("agent-join", "a", {"strengths": []}),
            ("manager-active", "mgr", None),
            ("thread-open", "mgr", {"id": "T1", "title": "one", "owner": "a"}),
            ("thread-open", "mgr", {"id": "T2", "title": "two"}),
        )
        plan = plan_auto_assign(st)
        self.assertEqual([tid for tid, _, _ in plan], ["T2"])

    def test_no_agents_means_empty_plan(self):
        st = build(("manager-active", "mgr", None),
                   ("thread-open", "mgr", {"id": "T1", "title": "x"}))
        self.assertEqual(plan_auto_assign(st), [])


if __name__ == "__main__":
    unittest.main()
