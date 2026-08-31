from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from agentmgr.events import Event
from agentmgr.state import reconcile


def _ev(event: str, actor: str, data=None, ts: str | None = None) -> Event:
    return Event(
        id=f"ULID{_ev.counter:04d}",
        ts=ts or "2026-08-31T12:00:00.000000Z",
        actor=actor,
        event=event,
        data=data or {},
    )


_ev.counter = 0


def seq(*events: Event) -> list[Event]:
    for i, e in enumerate(events):
        object.__setattr__(e, "id", f"ULID{i:04d}")
    return list(events)


class ReconcileTests(unittest.TestCase):
    def test_idle_when_no_events(self) -> None:
        self.assertEqual(reconcile([]).mode, "IDLE")

    def test_claim_solo_enters_solo_mode(self) -> None:
        st = reconcile(seq(_ev("claim-solo", "claude-01")))
        self.assertEqual(st.mode, "SOLO(claude-01)")
        self.assertTrue(st.agents["claude-01"].solo)

    def test_manager_active_enters_managed(self) -> None:
        st = reconcile(seq(
            _ev("claim-solo", "claude-01"),
            _ev("manager-active", "manager"),
        ))
        self.assertEqual(st.mode, "MANAGED")

    def test_manager_idle_releases_control(self) -> None:
        st = reconcile(seq(
            _ev("manager-active", "manager"),
            _ev("manager-idle", "manager"),
            _ev("claim-solo", "gpt-01"),
        ))
        self.assertEqual(st.mode, "SOLO(gpt-01)")

    def test_two_solo_claims_without_manager_is_contested(self) -> None:
        st = reconcile(seq(
            _ev("claim-solo", "claude-01"),
            _ev("claim-solo", "gpt-01"),
        ))
        self.assertEqual(st.mode, "CONTESTED")

    def test_charter_ack_records_version(self) -> None:
        st = reconcile(seq(_ev("charter-ack", "claude-01", {"version": 3})))
        self.assertEqual(st.agents["claude-01"].charter_ack, 3)

    def test_handoff_transfers_solo_ownership(self) -> None:
        st = reconcile(seq(
            _ev("claim-solo", "claude-01"),
            _ev("handoff-created", "claude-01", {"id": "H1", "from": "claude-01", "to": "gpt-01"}),
            _ev("handoff-accepted", "gpt-01", {"id": "H1", "to": "gpt-01"}),
        ))
        self.assertEqual(st.mode, "SOLO(gpt-01)")
        self.assertFalse(st.agents["claude-01"].solo)
        self.assertEqual(st.pending_handoffs, [])

    def test_thread_lifecycle(self) -> None:
        st = reconcile(seq(
            _ev("thread-open", "claude-01", {"id": "T1", "title": "Parser"}),
            _ev("thread-update", "claude-01", {"id": "T1", "status": "blocked", "next_step": "schema"}),
            _ev("thread-open", "claude-01", {"id": "T2", "title": "CLI"}),
            _ev("thread-close", "claude-01", {"id": "T2"}),
        ))
        self.assertEqual(st.threads["T1"].status, "blocked")
        self.assertEqual(st.threads["T1"].next_step, "schema")
        self.assertEqual(st.threads["T2"].status, "done")
        self.assertEqual([t.id for t in st.open_threads()], ["T1"])

    def test_stale_agent_detection(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        st = reconcile(seq(_ev("claim-solo", "claude-01", ts=old)))
        self.assertIn("claude-01", st.stale_agents(90))
        self.assertNotIn("claude-01", st.stale_agents(90, now=datetime.now(timezone.utc) - timedelta(hours=5)))


if __name__ == "__main__":
    unittest.main()
