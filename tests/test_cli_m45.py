from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from agentmgr import cli
from agentmgr.cli import main
from agentmgr.events import Event, read_events
from agentmgr.paths import Layout
from agentmgr.scaffold import init_project
from agentmgr.state import reconcile


class M45CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._cwd = os.getcwd()
        os.chdir(self.root)
        init_project(self.root, project_name="demo")

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def events_of(self, kind: str):
        return [e for e in read_events(Layout(self.root)) if e.event == kind]

    def _new_handoff(self) -> str:
        self.cli("handoff", "new", "--from", "claude-01", "--to", "gpt-01")
        return next((self.root / ".agentmgr" / "HANDOFF").glob("*.md")).stem.split("-", 1)[0]

    # --- config knobs -----------------------------------------------------
    def test_init_writes_split_thresholds(self) -> None:
        cfg = json.loads((self.root / ".agentmgr" / "config.json").read_text(encoding="utf-8"))
        self.assertIn("thread_stale_minutes", cfg)
        self.assertIn("manager_stale_minutes", cfg)
        self.assertIn("verify_command", cfg)

    # --- handoff placeholder gate --------------------------------------------
    def test_accept_refuses_packet_with_placeholders(self) -> None:
        hid = self._new_handoff()
        rc, _, err = self.cli("handoff", "accept", hid, "--as", "gpt-01")
        self.assertEqual(rc, 1)
        self.assertIn("unfilled placeholders", err)
        self.assertEqual(self.events_of("handoff-accepted"), [])

    def test_accept_force_bypasses_gate(self) -> None:
        hid = self._new_handoff()
        rc, _, _ = self.cli("handoff", "accept", hid, "--as", "gpt-01", "--force")
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.events_of("handoff-accepted")), 1)

    def test_accept_warns_when_taker_has_no_charter_ack(self) -> None:
        hid = self._new_handoff()
        rc, _, err = self.cli("handoff", "accept", hid, "--as", "gpt-01", "--force")
        self.assertEqual(rc, 0)
        self.assertIn("no charter-ack on record", err)

    # --- check ------------------------------------------------------------
    def test_check_records_pass(self) -> None:
        rc, out, _ = self.cli("check", "--command", "python -c \"raise SystemExit(0)\"", "--as", "claude-01")
        self.assertEqual(rc, 0)
        self.assertIn("PASS", out)
        (ev,) = self.events_of("check-run")
        self.assertTrue(ev.data["ok"])
        self.assertEqual(ev.data["exit_code"], 0)

    def test_check_records_failure_and_returns_1(self) -> None:
        rc, out, _ = self.cli("check", "--command", "python -c \"raise SystemExit(3)\"", "--phase", "pre")
        self.assertEqual(rc, 1)
        self.assertIn("FAIL", out)
        (ev,) = self.events_of("check-run")
        self.assertFalse(ev.data["ok"])
        self.assertEqual(ev.data["exit_code"], 3)
        self.assertEqual(ev.data["phase"], "pre")

    def test_status_shows_last_check(self) -> None:
        self.cli("check", "--command", "python -c \"raise SystemExit(0)\"")
        _, out, _ = self.cli("status")
        self.assertIn("last check", out)
        self.assertIn("PASS", out)

    # --- stale manager --------------------------------------------------
    def test_manager_is_stale_helper(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        state = reconcile([Event(id="U0", ts=old, actor="mgr-01", event="manager-active", data={})])
        self.assertTrue(cli._manager_is_stale(state, 15))
        self.assertFalse(cli._manager_is_stale(state, 90))

    def test_claim_solo_still_noop_under_fresh_manager(self) -> None:
        self.cli("manager", "start", "--as", "mgr-01")
        rc, out, _ = self.cli("claim-solo", "claude-01")
        self.assertIn("safe no-op", out)
        self.assertNotIn("claude-01", reconcile(read_events(Layout(self.root))).agents)

    def test_verify_after_m45_flow(self) -> None:
        self.cli("check", "--command", "python -c \"raise SystemExit(0)\"")
        hid = self._new_handoff()
        self.cli("handoff", "accept", hid, "--as", "gpt-01", "--force")
        rc, out, _ = self.cli("verify")
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main()
