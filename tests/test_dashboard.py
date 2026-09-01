from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

from agentmgr.cli import main
from agentmgr.dashboard import build_state, make_server
from agentmgr.paths import Layout
from agentmgr.scaffold import init_project


class BuildStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._cwd = os.getcwd()
        os.chdir(self.root)
        init_project(self.root, project_name="demo")

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def cli(self, *argv: str) -> int:
        import io
        from contextlib import redirect_stderr, redirect_stdout

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main(list(argv))

    def test_shape_of_empty_project(self) -> None:
        d = build_state(Layout(self.root))
        for key in ("project", "mode", "agents", "threads", "findings", "recent_events", "ledger_head"):
            self.assertIn(key, d)
        self.assertEqual(d["mode"], "IDLE")
        self.assertEqual(d["agents"], [])

    def test_reflects_events(self) -> None:
        self.cli("charter-ack", "claude-01")
        self.cli("claim-solo", "claude-01")
        self.cli("thread", "add", "T1", "--title", "Parser", "--actor", "claude-01")
        self.cli("check", "--command", "python -c \"raise SystemExit(0)\"")
        d = build_state(Layout(self.root))
        self.assertEqual(d["mode"], "SOLO(claude-01)")
        self.assertEqual(d["agents"][0]["actor"], "claude-01")
        self.assertEqual(d["threads"][0]["id"], "T1")
        self.assertTrue(d["last_check"]["ok"])
        self.assertTrue(any(e["event"] == "thread-open" for e in d["recent_events"]))

    def test_does_not_write_anything(self) -> None:
        self.cli("claim-solo", "claude-01")
        events_dir = self.root / ".agentmgr" / "events"
        before = {p.name for p in events_dir.iterdir()}
        build_state(Layout(self.root))
        build_state(Layout(self.root))
        self.assertEqual({p.name for p in events_dir.iterdir()}, before)


class HttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        init_project(self.root, project_name="demo")
        self.httpd = make_server(Layout(self.root), "127.0.0.1", 0, 2)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self._tmp.cleanup()

    def _get(self, path: str) -> tuple[int, str, str]:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read().decode("utf-8")

    def test_index_serves_html(self) -> None:
        status, ctype, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn("agentmgr dashboard", body)
        self.assertNotIn("__INTERVAL__", body)  # token was substituted

    def test_api_state_serves_json(self) -> None:
        status, ctype, body = self._get("/api/state")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        self.assertEqual(json.loads(body)["mode"], "IDLE")

    def test_unknown_path_404(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/nope")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
