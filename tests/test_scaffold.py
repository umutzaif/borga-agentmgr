import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agentmgr.scaffold import init_project


class InitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_creates_directory_tree(self) -> None:
        layout = init_project(self.root, project_name="demo")
        for path in (layout.events, layout.archive, layout.handoff):
            self.assertTrue(path.is_dir(), path)
        for path in (layout.charter, layout.style, layout.agents, layout.bootstrap, layout.config):
            self.assertTrue(path.is_file(), path)

    def test_config_records_project_name_and_threshold(self) -> None:
        layout = init_project(self.root, project_name="demo")
        cfg = json.loads(layout.config.read_text(encoding="utf-8"))
        self.assertEqual(cfg["project"], "demo")
        self.assertEqual(cfg["heartbeat_stale_minutes"], 90)

    def test_refuses_to_reinit_without_force(self) -> None:
        init_project(self.root)
        with self.assertRaises(FileExistsError):
            init_project(self.root)

    def test_force_refreshes_templates_but_keeps_events(self) -> None:
        layout = init_project(self.root)
        (layout.events / "keep.json").write_text("{}", encoding="utf-8")
        layout.charter.write_text("edited", encoding="utf-8")
        init_project(self.root, force=True)
        self.assertTrue((layout.events / "keep.json").exists())
        self.assertNotEqual(layout.charter.read_text(encoding="utf-8"), "edited")


if __name__ == "__main__":
    unittest.main()
