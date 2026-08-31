import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from agentmgr.cli import main
from agentmgr.events import read_events
from agentmgr.paths import Layout
from agentmgr.scaffold import init_project
from agentmgr.state import reconcile


class M2CliTests(unittest.TestCase):
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

    def state(self):
        return reconcile(read_events(Layout(self.root)))

    def test_charter_ack_reads_version_and_hash(self) -> None:
        rc, out, _ = self.cli("charter-ack", "claude-01")
        self.assertEqual(rc, 0)
        ag = self.state().agents["claude-01"]
        self.assertEqual(ag.charter_ack, 1)
        (ev,) = [e for e in read_events(Layout(self.root)) if e.event == "charter-ack"]
        self.assertEqual(len(ev.data["sha256"]), 64)

    def test_claim_solo_is_noop_when_manager_active(self) -> None:
        self.cli("log", "manager-active", "--actor", "mgr")
        rc, out, _ = self.cli("claim-solo", "claude-01")
        self.assertEqual(rc, 0)
        self.assertIn("safe no-op", out)
        self.assertNotIn("claude-01", self.state().agents)

    def test_claim_solo_warns_on_contention(self) -> None:
        self.cli("claim-solo", "claude-01")
        rc, _, err = self.cli("claim-solo", "gpt-01")
        self.assertEqual(rc, 0)
        self.assertIn("CONTESTED", err)
        self.assertEqual(self.state().mode, "CONTESTED")

    def test_reconcile_clean_project(self) -> None:
        self.cli("charter-ack", "claude-01")
        self.cli("claim-solo", "claude-01")
        rc, out, _ = self.cli("reconcile")
        self.assertEqual(rc, 0)
        self.assertIn("no issues", out)

    def test_reconcile_strict_flags_contention(self) -> None:
        self.cli("claim-solo", "claude-01")
        self.cli("claim-solo", "gpt-01")
        rc, out, _ = self.cli("reconcile", "--strict")
        self.assertEqual(rc, 1)
        self.assertIn("CONTESTED", out)

    def test_reconcile_flags_uncommitted_agent(self) -> None:
        self.cli("claim-solo", "claude-01")  # no charter-ack
        rc, out, _ = self.cli("reconcile")
        self.assertIn("no charter-ack", out)

    def test_join_records_profile_and_updates_config(self) -> None:
        rc, _, _ = self.cli("join", "gpt-01", "--provider", "OpenAI", "--strengths", "tests, speed")
        self.assertEqual(rc, 0)
        (ev,) = [e for e in read_events(Layout(self.root)) if e.event == "agent-join"]
        self.assertEqual(ev.data["provider"], "OpenAI")
        self.assertEqual(ev.data["strengths"], ["tests", "speed"])
        cfg = json.loads((self.root / ".agentmgr" / "config.json").read_text(encoding="utf-8"))
        self.assertIn("gpt-01", cfg["actors"])

    def test_heartbeat_appends_event(self) -> None:
        self.cli("heartbeat", "claude-01")
        events = [e for e in read_events(Layout(self.root)) if e.event == "heartbeat"]
        self.assertEqual(len(events), 1)

    def test_missing_project_exits_2(self) -> None:
        with TemporaryDirectory() as empty:
            os.chdir(empty)
            try:
                rc, _, err = self.cli("status")
            finally:
                os.chdir(self._cwd)  # release the dir so Windows can delete it
            self.assertEqual(rc, 2)
            self.assertIn("agentmgr init", err)


if __name__ == "__main__":
    unittest.main()
