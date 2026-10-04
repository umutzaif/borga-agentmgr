"""A project found far above the cwd (or in the home directory) is adopted with a warning."""

from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from agentmgr.cli import main
from agentmgr.paths import MAX_UPWARD_LEVELS, QUIET_ENV, distant_root_warning
from agentmgr.scaffold import init_project


class RootWarningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self._cwd = os.getcwd()
        init_project(self.root, project_name="demo")
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(QUIET_ENV, None)

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def nested(self, levels: int) -> Path:
        path = self.root.joinpath(*[f"d{i}" for i in range(levels)])
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    # --- the pure check --------------------------------------------------
    def test_no_warning_when_cwd_is_the_project_root(self) -> None:
        self.assertIsNone(distant_root_warning(self.root, self.root))

    def test_no_warning_for_a_nearby_subdirectory(self) -> None:
        self.assertIsNone(distant_root_warning(self.nested(MAX_UPWARD_LEVELS), self.root))

    def test_warns_when_the_root_is_far_above(self) -> None:
        note = distant_root_warning(self.nested(MAX_UPWARD_LEVELS + 1), self.root)
        self.assertIn(f"{MAX_UPWARD_LEVELS + 1} levels above", note)
        self.assertIn(str(self.root), note)

    def test_warns_when_the_root_is_the_home_directory_even_if_close(self) -> None:
        with mock.patch("agentmgr.paths._home", return_value=self.root):
            note = distant_root_warning(self.nested(1), self.root)
        self.assertIn("your home directory", note)

    def test_home_directory_as_cwd_does_not_warn(self) -> None:
        with mock.patch("agentmgr.paths._home", return_value=self.root):
            self.assertIsNone(distant_root_warning(self.root, self.root))

    def test_env_var_silences_it(self) -> None:
        os.environ[QUIET_ENV] = "1"
        self.assertIsNone(distant_root_warning(self.nested(MAX_UPWARD_LEVELS + 2), self.root))

    # --- through the CLI -------------------------------------------------
    def test_status_from_a_far_subdirectory_warns_on_stderr_and_still_works(self) -> None:
        os.chdir(self.nested(MAX_UPWARD_LEVELS + 1))
        rc, out, err = self.cli("status")
        self.assertEqual(rc, 0)
        self.assertIn("levels above here", err)
        self.assertNotIn("warning", out)

    def test_log_command_warns_too(self) -> None:
        os.chdir(self.nested(MAX_UPWARD_LEVELS + 1))
        rc, _, err = self.cli("log", "heartbeat", "--actor", "a")
        self.assertEqual(rc, 0)
        self.assertIn("levels above here", err)

    def test_status_from_the_project_root_is_quiet(self) -> None:
        os.chdir(self.root)
        rc, _, err = self.cli("status")
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
