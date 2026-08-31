import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agentmgr.charter import charter_fingerprint
from agentmgr.paths import Layout
from agentmgr.scaffold import init_project


class CharterFingerprintTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_reads_template_version(self) -> None:
        layout = init_project(self.root)
        version, digest = charter_fingerprint(layout)
        self.assertEqual(version, 1)
        self.assertEqual(len(digest), 64)

    def test_hash_changes_with_content(self) -> None:
        layout = init_project(self.root)
        _, before = charter_fingerprint(layout)
        layout.charter.write_text(
            layout.charter.read_text(encoding="utf-8") + "\nextra\n", encoding="utf-8"
        )
        _, after = charter_fingerprint(layout)
        self.assertNotEqual(before, after)

    def test_bumped_version_is_detected(self) -> None:
        layout = init_project(self.root)
        layout.charter.write_text(
            layout.charter.read_text(encoding="utf-8").replace("**Sürüm:** 1", "**Sürüm:** 7"),
            encoding="utf-8",
        )
        version, _ = charter_fingerprint(layout)
        self.assertEqual(version, 7)

    def test_missing_charter_returns_none(self) -> None:
        layout = Layout(self.root)
        self.assertEqual(charter_fingerprint(layout), (None, None))


if __name__ == "__main__":
    unittest.main()
