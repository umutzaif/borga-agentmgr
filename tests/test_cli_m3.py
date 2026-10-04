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


class M3CliTests(unittest.TestCase):
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

    def _new_handoff(self, fill: bool = True) -> str:
        rc, out, _ = self.cli("handoff", "new", "--from", "claude-01", "--to", "gpt-01")
        self.assertEqual(rc, 0, out)
        docs = list((self.root / ".agentmgr" / "HANDOFF").glob("*.md"))
        self.assertEqual(len(docs), 1)
        if fill:  # replace the _<...>_ placeholders so 'accept' does not gate
            import re

            text = re.sub(r"_<[^<>]*>_", "done", docs[0].read_text(encoding="utf-8"))
            docs[0].write_text(text, encoding="utf-8")
        return docs[0].stem.split("-", 1)[0]

    def test_handoff_new_creates_doc_and_event(self) -> None:
        hid = self._new_handoff()
        created = [e for e in read_events(Layout(self.root)) if e.event == "handoff-created"]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].data["id"], hid)
        self.assertEqual(created[0].data["to"], "gpt-01")

    def test_handoff_accept_transfers_ownership(self) -> None:
        self.cli("claim-solo", "claude-01")
        hid = self._new_handoff()
        rc, out, _ = self.cli("handoff", "accept", hid, "--as", "gpt-01")
        self.assertEqual(rc, 0, out)
        st = self.state()
        self.assertEqual(st.mode, "SOLO(gpt-01)")
        self.assertFalse(st.agents["claude-01"].solo)

    def test_accept_infers_target_from_created_event(self) -> None:
        hid = self._new_handoff()
        rc, out, _ = self.cli("handoff", "accept", hid)  # no --as
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.state().mode, "SOLO(gpt-01)")

    def test_accept_twice_is_noop(self) -> None:
        hid = self._new_handoff()
        self.cli("handoff", "accept", hid, "--as", "gpt-01")
        rc, out, _ = self.cli("handoff", "accept", hid, "--as", "gpt-01")
        self.assertEqual(rc, 0)
        self.assertIn("already accepted", out)
        accepted = [e for e in read_events(Layout(self.root)) if e.event == "handoff-accepted"]
        self.assertEqual(len(accepted), 1)

    def test_handoff_list_reflects_status(self) -> None:
        hid = self._new_handoff()
        _, out, _ = self.cli("handoff", "list")
        self.assertIn("PENDING", out)
        self.cli("handoff", "accept", hid, "--as", "gpt-01")
        _, out, _ = self.cli("handoff", "list")
        self.assertIn("accepted", out)
        self.assertNotIn("PENDING", out)

    def test_accept_unknown_id_errors(self) -> None:
        rc, _, err = self.cli("handoff", "accept", "does-not-exist")
        self.assertEqual(rc, 1)
        self.assertIn("no handoff matching", err)

    def test_thread_add_update_close_flow(self) -> None:
        self.cli("thread", "add", "T1", "--title", "Parser", "--actor", "claude-01", "--next", "lexer")
        self.assertEqual(self.state().threads["T1"].next_step, "lexer")
        self.cli("thread", "update", "T1", "--actor", "claude-01", "--status", "blocked")
        self.assertEqual(self.state().threads["T1"].status, "blocked")
        self.cli("thread", "close", "T1", "--actor", "claude-01")
        self.assertEqual(self.state().threads["T1"].status, "done")
        threads_md = (self.root / ".agentmgr" / "THREADS.md").read_text(encoding="utf-8")
        self.assertIn("T1", threads_md)

    def test_thread_update_requires_a_field(self) -> None:
        self.cli("thread", "add", "T1", "--title", "x", "--actor", "a")
        rc, _, err = self.cli("thread", "update", "T1", "--actor", "a")
        self.assertEqual(rc, 1)
        self.assertIn("nothing to update", err)

    def test_ledger_verifies_after_m3_flow(self) -> None:
        self.cli("claim-solo", "claude-01")
        hid = self._new_handoff()
        self.cli("handoff", "accept", hid, "--as", "gpt-01")
        self.cli("thread", "add", "T1", "--title", "x", "--actor", "gpt-01")
        rc, out, _ = self.cli("verify")
        self.assertEqual(rc, 0, out)
        self.assertIn("chain intact", out)


if __name__ == "__main__":
    unittest.main()
