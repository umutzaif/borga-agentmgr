import io
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


class M4CliTests(unittest.TestCase):
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

    def events_of(self, kind: str):
        return [e for e in read_events(Layout(self.root)) if e.event == kind]

    def test_manager_start_enters_managed(self) -> None:
        rc, _, _ = self.cli("manager", "start", "--as", "mgr-01")
        self.assertEqual(rc, 0)
        self.assertEqual(self.state().mode, "MANAGED")
        self.assertEqual(self.state().manager, "mgr-01")

    def test_manager_start_twice_same_actor_is_noop(self) -> None:
        self.cli("manager", "start", "--as", "mgr-01")
        rc, out, _ = self.cli("manager", "start", "--as", "mgr-01")
        self.assertEqual(rc, 0)
        self.assertIn("already the active manager", out)
        self.assertEqual(len(self.events_of("manager-active")), 1)

    def test_manager_stop_releases_control(self) -> None:
        self.cli("manager", "start", "--as", "mgr-01")
        self.cli("manager", "stop", "--as", "mgr-01")
        self.assertIsNone(self.state().manager)
        self.assertEqual(self.state().mode, "IDLE")

    def test_manager_stop_by_wrong_actor_warns(self) -> None:
        self.cli("manager", "start", "--as", "mgr-01")
        rc, _, err = self.cli("manager", "stop", "--as", "someone-else")
        self.assertEqual(rc, 0)
        self.assertIn("active manager is mgr-01", err)

    def test_manager_run_once_stamps_active_then_idle(self) -> None:
        rc, out, _ = self.cli("manager", "run", "--as", "mgr-01", "--once")
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.events_of("manager-active")), 1)
        self.assertEqual(len(self.events_of("manager-idle")), 1)
        self.assertIsNone(self.state().manager)  # restored to idle on exit
        self.assertIn("mgr-01 idle", out)

    def test_manager_run_once_reports_findings(self) -> None:
        self.cli("claim-solo", "claude-01")  # no charter-ack -> a finding
        rc, out, _ = self.cli("manager", "run", "--as", "mgr-01", "--once")
        self.assertIn("no charter-ack", out)

    def test_manager_run_once_does_not_emit_heartbeat(self) -> None:
        self.cli("manager", "run", "--as", "mgr-01", "--once")
        self.assertEqual(self.events_of("heartbeat"), [])

    def test_watch_once_renders_without_writing(self) -> None:
        self.cli("charter-ack", "claude-01")
        before = len(read_events(Layout(self.root)))
        rc, out, _ = self.cli("watch", "--once", "--no-clear")
        self.assertEqual(rc, 0)
        self.assertIn("Agent Manager", out)
        self.assertIn("watching", out)
        self.assertEqual(len(read_events(Layout(self.root))), before)

    def test_ledger_verifies_after_manager_cycle(self) -> None:
        self.cli("claim-solo", "claude-01")
        self.cli("manager", "run", "--as", "mgr-01", "--once")
        rc, out, _ = self.cli("verify")
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main()
