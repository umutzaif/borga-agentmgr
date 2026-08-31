from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from agentmgr.events import Event
from agentmgr.report import findings
from agentmgr.state import reconcile


def seq(*specs: tuple[str, str, dict | None], base_ts: str = "2026-08-31T12:00:00.000000Z"):
    events = []
    for i, (event, actor, data) in enumerate(specs):
        events.append(Event(id=f"ULID{i:04d}", ts=base_ts, actor=actor, event=event, data=data or {}))
    return events


class FindingsTests(unittest.TestCase):
    def test_clean_state_has_no_findings(self) -> None:
        state = reconcile(seq(
            ("charter-ack", "claude-01", {"version": 1}),
            ("claim-solo", "claude-01", None),
        ))
        self.assertEqual(findings(state, 90), [])

    def test_flags_uncommitted_active_agent(self) -> None:
        state = reconcile(seq(("claim-solo", "claude-01", None)))
        self.assertTrue(any("no charter-ack" in f for f in findings(state, 90)))

    def test_flags_contested_mode(self) -> None:
        state = reconcile(seq(
            ("charter-ack", "a", {"version": 1}),
            ("claim-solo", "a", None),
            ("charter-ack", "b", {"version": 1}),
            ("claim-solo", "b", None),
        ))
        self.assertTrue(any("CONTESTED" in f for f in findings(state, 90)))

    def test_flags_orphaned_solo_claim_past_threshold(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        state = reconcile(seq(
            ("charter-ack", "claude-01", {"version": 1}),
            ("claim-solo", "claude-01", None),
            base_ts=old,
        ))
        self.assertTrue(any("orphaned solo claim" in f for f in findings(state, 90)))

    def test_flags_stale_open_thread(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        state = reconcile(seq(
            ("thread-open", "claude-01", {"id": "T1", "title": "Parser"}),
            base_ts=old,
        ))
        self.assertTrue(any("stale thread T1" in f for f in findings(state, 90)))


if __name__ == "__main__":
    unittest.main()
