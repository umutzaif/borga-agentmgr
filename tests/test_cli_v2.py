from __future__ import annotations

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


class V2CliTests(unittest.TestCase):
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

    def _team(self) -> None:
        self.cli("join", "claude-01", "--provider", "Anthropic", "--strengths", "architecture, parser")
        self.cli("join", "gpt-01", "--provider", "OpenAI", "--strengths", "tests, speed")
        self.cli("manager", "start", "--as", "mgr-01")
        self.cli("thread", "add", "T1", "--title", "Parser", "--actor", "mgr-01", "--tags", "parser")
        self.cli("thread", "add", "T2", "--title", "Tests", "--actor", "mgr-01", "--tags", "tests")

    # --- assign ---------------------------------------------------------
    def test_assign_explicit(self) -> None:
        self._team()
        rc, out, _ = self.cli("assign", "T1", "--to", "claude-01")
        self.assertEqual(rc, 0)
        self.assertEqual(self.state().threads["T1"].owner, "claude-01")

    def test_assign_needs_manager_or_as(self) -> None:
        self.cli("thread", "add", "T1", "--title", "x", "--actor", "someone")
        rc, _, err = self.cli("assign", "T1", "--to", "a")
        self.assertEqual(rc, 1)
        self.assertIn("no active manager", err)

    def test_assign_auto_matches_tags(self) -> None:
        self._team()
        rc, out, _ = self.cli("assign", "--auto")
        self.assertEqual(rc, 0)
        st = self.state()
        self.assertEqual(st.threads["T1"].owner, "claude-01")
        self.assertEqual(st.threads["T2"].owner, "gpt-01")
        self.assertEqual(st.mode, "TEAM")

    def test_assign_auto_dry_run_writes_nothing(self) -> None:
        self._team()
        before = len(read_events(Layout(self.root)))
        rc, out, _ = self.cli("assign", "--auto", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("dry run", out)
        self.assertEqual(len(read_events(Layout(self.root))), before)

    # --- decisions ----------------------------------------------------
    def test_decision_propose_ratify_list(self) -> None:
        rc, out, _ = self.cli("decision", "propose", "--as", "claude-01", "--title", "use JSONL", "--id", "D1")
        self.assertEqual(rc, 0)
        self.assertEqual(self.state().decisions["D1"].status, "proposed")

        rc, out, _ = self.cli("decision", "ratify", "D1", "--as", "gpt-01")
        self.assertEqual(rc, 0)
        self.assertEqual(self.state().decisions["D1"].status, "ratified")

        rc, out, _ = self.cli("decision", "list")
        self.assertIn("D1", out)
        self.assertIn("ratified", out)

    def test_decision_ratify_twice_is_noop(self) -> None:
        self.cli("decision", "propose", "--as", "a", "--title", "x", "--id", "D1")
        self.cli("decision", "ratify", "D1", "--as", "b")
        rc, out, _ = self.cli("decision", "ratify", "D1", "--as", "b")
        self.assertEqual(rc, 0)
        self.assertIn("already ratified", out)
        self.assertEqual(len([e for e in read_events(Layout(self.root)) if e.event == "decision-ratified"]), 1)

    def test_decision_ratify_unknown(self) -> None:
        rc, _, err = self.cli("decision", "ratify", "nope", "--as", "a")
        self.assertEqual(rc, 1)
        self.assertIn("no decision matching", err)

    # --- integrate --------------------------------------------------
    def test_integrate_not_ready_with_open_threads(self) -> None:
        self._team()
        self.cli("assign", "--auto")
        rc, out, _ = self.cli("integrate")
        self.assertIn("NOT ready", out)
        self.assertIn("still open", out)

    def test_integrate_ready_after_close_and_check(self) -> None:
        self._team()
        self.cli("assign", "--auto")
        self.cli("thread", "close", "T1", "--actor", "claude-01")
        self.cli("thread", "close", "T2", "--actor", "gpt-01")
        self.cli("check", "--command", "python -c \"raise SystemExit(0)\"", "--as", "mgr-01")
        rc, out, _ = self.cli("integrate", "--strict")
        self.assertEqual(rc, 0, out)
        self.assertIn("READY to integrate", out)

    def test_integrate_blocked_by_pending_decision(self) -> None:
        self.cli("thread", "add", "T1", "--title", "x", "--actor", "a")
        self.cli("thread", "close", "T1", "--actor", "a")
        self.cli("check", "--command", "python -c \"raise SystemExit(0)\"")
        self.cli("decision", "propose", "--as", "a", "--title", "unresolved", "--id", "D9")
        rc, out, _ = self.cli("integrate", "--strict")
        self.assertEqual(rc, 1)
        self.assertIn("D9 still pending", out)

    def test_verify_after_v2_flow(self) -> None:
        self._team()
        self.cli("assign", "--auto")
        self.cli("decision", "propose", "--as", "mgr-01", "--title", "x", "--id", "D1")
        self.cli("decision", "ratify", "D1", "--as", "claude-01")
        rc, out, _ = self.cli("verify")
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main()
