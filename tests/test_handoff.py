import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from agentmgr.events import Event
from agentmgr.handoff import create_handoff, find_handoff
from agentmgr.scaffold import init_project
from agentmgr.state import reconcile


def _ev(i: int, event: str, actor: str, data=None) -> Event:
    return Event(id=f"ULID{i:04d}", ts="2026-08-31T12:00:00.000000Z",
                 actor=actor, event=event, data=data or {})


class HandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.layout = init_project(Path(self._tmp.name), project_name="demo")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_create_writes_file_and_returns_id(self) -> None:
        hid, path = create_handoff(self.layout, "claude-01", "gpt-01", [], reconcile([]))
        self.assertTrue(path.exists())
        self.assertTrue(path.stem.startswith(hid))
        self.assertIn("-to-gpt-01", path.stem)

    def test_create_rejects_same_actor(self) -> None:
        with self.assertRaises(ValueError):
            create_handoff(self.layout, "a", "a", [], reconcile([]))

    def test_document_embeds_charter_version_and_open_threads(self) -> None:
        events = [
            _ev(0, "thread-open", "claude-01", {"id": "T1", "title": "Parser"}),
            _ev(1, "thread-update", "claude-01", {"id": "T1", "next_step": "tokeniser"}),
        ]
        _, path = create_handoff(self.layout, "claude-01", "gpt-01", events, reconcile(events))
        text = path.read_text(encoding="utf-8")
        self.assertIn("Charter:** v1", text)
        self.assertIn("### T1 - Parser", text)
        self.assertIn("tokeniser", text)

    def test_document_notes_when_no_threads(self) -> None:
        _, path = create_handoff(self.layout, "a", "b", [], reconcile([]))
        self.assertIn("Acik thread yok", path.read_text(encoding="utf-8"))

    def test_find_by_prefix(self) -> None:
        hid, path = create_handoff(self.layout, "a", "b", [], reconcile([]),
                                   now=datetime(2026, 8, 31, 12, 48, 0, tzinfo=timezone.utc))
        self.assertEqual(find_handoff(self.layout, hid), path)
        self.assertEqual(find_handoff(self.layout, "20260831"), path)

    def test_find_ambiguous_raises(self) -> None:
        create_handoff(self.layout, "a", "b", [], reconcile([]),
                       now=datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc))
        create_handoff(self.layout, "a", "c", [], reconcile([]),
                       now=datetime(2026, 8, 31, 13, 0, 0, tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            find_handoff(self.layout, "2026")

    def test_find_missing_returns_none(self) -> None:
        self.assertIsNone(find_handoff(self.layout, "nope"))


if __name__ == "__main__":
    unittest.main()
