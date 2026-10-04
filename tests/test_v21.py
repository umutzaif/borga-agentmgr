"""v2.1 field fixes - one test group per finding from the e-commerce pilot."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from agentmgr.cli import heartbeat_gap, main
from agentmgr.events import Event, read_events
from agentmgr.fanout import plan_auto_assign
from agentmgr.handoff import _decisions_block, _file_tree, _in_own_repo, create_handoff, unfilled_sections
from agentmgr.paths import Layout
from agentmgr.scaffold import init_project
from agentmgr.state import reconcile

_TS = "%Y-%m-%dT%H:%M:%S.%fZ"


def ev(i, event, actor, data=None):
    return Event(id=f"U{i:04d}", ts="2026-09-01T10:00:00.000000Z", actor=actor, event=event, data=data or {})


def build(*specs):
    return reconcile([ev(i, *s) for i, s in enumerate(specs)])


class CliCase(unittest.TestCase):
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


class HandoffAcceptTests(CliCase):
    def _handoff(self, frm: str, to: str) -> str:
        _, out, _ = self.cli("handoff", "new", "--from", frm, "--to", to)
        return next(w for w in out.split() if w.endswith(f"-{frm}-to-{to}.md")).split("/")[-1].split("-", 1)[0]

    def test_accept_moves_open_threads_of_the_outgoing_agent(self) -> None:
        self.cli("manager", "start", "--as", "mgr")
        for tid, owner in (("T1", "a"), ("T2", "a"), ("T3", "c")):
            self.cli("thread", "add", tid, "--title", tid, "--actor", "mgr", "--owner", owner)
        self.cli("thread", "close", "T2", "--actor", "a")
        hid = self._handoff("a", "b")

        rc, out, _ = self.cli("handoff", "accept", hid, "--as", "b", "--force")

        self.assertEqual(rc, 0)
        threads = self.state().threads
        self.assertEqual(threads["T1"].owner, "b")      # open, was a's -> moved
        self.assertEqual(threads["T2"].owner, "a")      # done -> untouched
        self.assertEqual(threads["T3"].owner, "c")      # someone else's -> untouched
        self.assertIn("threads moved from a to b: T1", out)

    def test_accept_under_manager_does_not_make_taker_solo(self) -> None:
        self.cli("manager", "start", "--as", "mgr")
        self.cli("thread", "add", "T1", "--title", "x", "--actor", "mgr", "--owner", "a")
        self.cli("thread", "add", "T2", "--title", "y", "--actor", "mgr", "--owner", "c")
        hid = self._handoff("a", "b")
        self.cli("handoff", "accept", hid, "--as", "b", "--force")

        st = self.state()
        self.assertFalse(any(a.solo for a in st.agents.values()))
        self.assertEqual(st.manager, "mgr")

    def test_accept_without_manager_is_still_solo(self) -> None:
        hid = self._handoff("a", "b")
        _, out, _ = self.cli("handoff", "accept", hid, "--as", "b", "--force")
        self.assertEqual(self.state().mode, "SOLO(b)")
        self.assertIn("SOLO(b)", out)


class PlaceholderGateTests(unittest.TestCase):
    def test_multiline_placeholder_is_detected(self) -> None:
        text = "## 1. Misyon\n\nfilled\n\n## 2. Kararlar\n\n_<satir bir\nsatir iki>_\n\n## 8. Son\n"
        self.assertEqual(unfilled_sections(text), ["2. Kararlar"])

    def test_text_with_angle_brackets_is_not_a_placeholder(self) -> None:
        text = "## 1. Misyon\n\nDELETE /api/cart/<product_id> ve a_b_c\n\n## 8. Son\n"
        self.assertEqual(unfilled_sections(text), [])


class HandoffContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.parent = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_project_nested_in_another_repo_gets_no_foreign_history(self) -> None:
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "init", "-q"], cwd=self.parent, check=True)
        (self.parent / "outer.txt").write_text("x", encoding="utf-8")
        subprocess.run([*git, "add", "."], cwd=self.parent, check=True)
        subprocess.run([*git, "commit", "-qm", "foreign commit"], cwd=self.parent, check=True)
        child = self.parent / "proj"
        child.mkdir()
        layout = init_project(child, project_name="proj")
        (child / "app.py").write_text("print(1)", encoding="utf-8")

        self.assertTrue(_in_own_repo(self.parent))
        self.assertFalse(_in_own_repo(child))
        _, path = create_handoff(layout, "a", "b", [], reconcile([]))
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("foreign commit", text)
        self.assertIn("_(git gecmisi yok)_", text)
        self.assertIn("app.py", text)

    def test_file_tree_honors_gitignore_and_skips_caches(self) -> None:
        layout = init_project(self.parent, project_name="proj")
        (self.parent / ".gitignore").write_text("data/*.db\n# comment\n", encoding="utf-8")
        for rel in ("app.py", "data/keep.txt", "data/shop.db", "pkg/__pycache__/m.cpython-312.pyc", "pkg/m.py"):
            target = self.parent / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x", encoding="utf-8")

        tree = _file_tree(layout.root).splitlines()

        self.assertIn("app.py", tree)
        self.assertIn("data/keep.txt", tree)
        self.assertIn("pkg/m.py", tree)
        self.assertNotIn("data/shop.db", tree)
        self.assertFalse([f for f in tree if "__pycache__" in f or f.endswith(".pyc")])
        self.assertFalse([f for f in tree if f.startswith(".agentmgr/")])


class DecisionBlockTests(unittest.TestCase):
    def test_ratified_line_shows_the_title_not_a_raw_dict(self) -> None:
        events = [
            ev(0, "decision-proposed", "a", {"id": "D1", "title": "DELETE rotasi ekle"}),
            ev(1, "decision-ratified", "mgr", {"id": "D1"}),
        ]
        block = _decisions_block(events)
        self.assertEqual(block.count("DELETE rotasi ekle"), 2)
        self.assertIn("onaylandi `D1`", block)
        self.assertNotIn("{'id'", block)


class ThreadStatusTests(CliCase):
    def test_log_rejects_unknown_thread_status(self) -> None:
        self.cli("thread", "add", "T1", "--title", "x", "--actor", "a")
        rc, _, err = self.cli(
            "log", "thread-update", "--actor", "a", "--data", '{"id": "T1", "status": "in_progress"}'
        )
        self.assertEqual(rc, 1)
        self.assertIn("invalid thread status", err)
        self.assertEqual(self.state().threads["T1"].status, "open")

    def test_log_accepts_known_statuses(self) -> None:
        self.cli("thread", "add", "T1", "--title", "x", "--actor", "a")
        for status in ("blocked", "open", "done"):
            rc, _, _ = self.cli(
                "log", "thread-update", "--actor", "a", "--data", '{"id": "T1", "status": "%s"}' % status
            )
            self.assertEqual(rc, 0)


class AutoAssignManagerTests(unittest.TestCase):
    def test_manager_gets_the_thread_it_matches_by_tag(self) -> None:
        st = build(
            ("agent-join", "claude", {"strengths": ["backend", "api"]}),
            ("agent-join", "gemini", {"strengths": ["frontend"]}),
            ("agent-join", "anti", {"strengths": ["testing"]}),
            ("manager-active", "claude", None),
            ("thread-open", "claude", {"id": "be", "title": "be", "tags": ["backend", "api"]}),
            ("thread-open", "claude", {"id": "fe", "title": "fe", "tags": ["frontend"]}),
            ("thread-open", "claude", {"id": "it", "title": "it", "tags": ["testing"]}),
        )
        plan = {tid: (agent, why) for tid, agent, why in plan_auto_assign(st)}
        self.assertEqual(plan["be"][0], "claude")
        self.assertIn("manager works too", plan["be"][1])
        self.assertEqual(plan["fe"][0], "gemini")
        self.assertEqual(plan["it"][0], "anti")

    def test_manager_is_not_used_for_unmatched_threads(self) -> None:
        st = build(
            ("agent-join", "claude", {"strengths": ["backend"]}),
            ("agent-join", "gemini", {"strengths": ["frontend"]}),
            ("manager-active", "claude", None),
            ("thread-open", "claude", {"id": "x", "title": "x", "tags": ["docs"]}),
        )
        self.assertEqual([agent for _, agent, _ in plan_auto_assign(st)], ["gemini"])

    def test_only_a_manager_joined_agent_can_work(self) -> None:
        st = build(
            ("manager-active", "claude", None),  # never joined
            ("thread-open", "claude", {"id": "x", "title": "x", "tags": ["backend"]}),
        )
        self.assertEqual(plan_auto_assign(st), [])


class ManagerHeartbeatTests(unittest.TestCase):
    def test_gap_is_a_third_of_the_stale_window_by_default(self) -> None:
        self.assertEqual(heartbeat_gap(30, 15), 300)
        self.assertEqual(heartbeat_gap(60, 15), 300)

    def test_gap_never_shorter_than_one_cycle(self) -> None:
        self.assertEqual(heartbeat_gap(600, 15), 600)

    def test_gap_scales_with_a_longer_stale_window(self) -> None:
        self.assertEqual(heartbeat_gap(60, 90), 1800)


class ManagerTakeoverTests(CliCase):
    def _old_manager(self, actor: str, minutes_ago: int) -> None:
        old = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime(_TS)
        with mock.patch("agentmgr.events.now_iso", return_value=old):
            self.cli("manager", "start", "--as", actor)

    def test_fresh_manager_cannot_be_taken_over_without_force(self) -> None:
        self.cli("manager", "start", "--as", "mgr")
        rc, _, err = self.cli("manager", "start", "--as", "intruder")
        self.assertEqual(rc, 1)
        self.assertIn("--force", err)
        self.assertEqual(self.state().manager, "mgr")

    def test_force_takes_over_and_records_it(self) -> None:
        self.cli("manager", "start", "--as", "mgr")
        rc, _, err = self.cli("manager", "start", "--as", "intruder", "--force")
        self.assertEqual(rc, 0)
        self.assertIn("WARNING", err)
        last = [e for e in read_events(Layout(self.root)) if e.event == "manager-active"][-1]
        self.assertEqual(last.data, {"takeover_from": "mgr", "forced": True})

    def test_stale_manager_takeover_is_allowed_but_visible(self) -> None:
        self._old_manager("mgr", 30)
        rc, _, err = self.cli("manager", "start", "--as", "backup")
        self.assertEqual(rc, 0)
        self.assertIn("stale manager mgr", err)
        st = self.state()
        self.assertEqual((st.manager, st.manager_takeover_from), ("backup", "mgr"))
        _, out, _ = self.cli("reconcile")
        self.assertIn("manager takeover: backup took over from mgr", out)

    def test_takeover_marker_clears_when_the_manager_goes_idle(self) -> None:
        self._old_manager("mgr", 30)
        self.cli("manager", "start", "--as", "backup")
        self.cli("manager", "stop", "--as", "backup")
        self.assertIsNone(self.state().manager_takeover_from)

    def test_manager_run_has_the_same_guard(self) -> None:
        self.cli("manager", "start", "--as", "mgr")
        rc, _, err = self.cli("manager", "run", "--as", "intruder", "--once")
        self.assertEqual(rc, 1)
        self.assertIn("--force", err)

    def test_manager_run_warns_when_interval_exceeds_stale_window(self) -> None:
        rc, _, err = self.cli("manager", "run", "--as", "mgr", "--once", "--interval", "99999")
        self.assertEqual(rc, 0)
        self.assertIn("will look stale between cycles", err)


if __name__ == "__main__":
    unittest.main()
