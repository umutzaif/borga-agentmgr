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
        self.assertTrue(any("stale thread T1" in f for f in findings(state, 90, thread_stale_minutes=90)))

    def test_thread_threshold_is_separate_from_solo(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        state = reconcile(seq(
            ("thread-open", "claude-01", {"id": "T1", "title": "Parser"}),
            base_ts=old,
        ))
        # default thread threshold (2 days) does not flag a 3h-old thread
        self.assertFalse(any("stale thread" in f for f in findings(state, 90)))

    def test_flags_stale_manager(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(minutes=40)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        state = reconcile(seq(("manager-active", "mgr-01", None), base_ts=old))
        self.assertTrue(any("stale manager" in f for f in findings(state, 90, manager_stale_minutes=15)))

    def test_flags_charter_drift(self) -> None:
        state = reconcile(seq(
            ("charter-ack", "claude-01", {"version": 1, "sha256": "aaaa1111"}),
            ("claim-solo", "claude-01", None),
        ))
        drift = findings(state, 90, charter_sha="bbbb2222")
        self.assertTrue(any("charter drift" in f for f in drift))
        # same sha -> no drift finding
        self.assertFalse(any("charter drift" in f for f in findings(state, 90, charter_sha="aaaa1111")))


if __name__ == "__main__":
    unittest.main()
