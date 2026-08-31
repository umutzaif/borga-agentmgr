import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agentmgr.events import append_event, read_events, sanitise_actor
from agentmgr.paths import Layout


class EventLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.layout = Layout(Path(self._tmp.name))
        self.layout.base.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_append_creates_one_file_per_event(self) -> None:
        append_event(self.layout, "claim-solo", "claude-desktop-01")
        append_event(self.layout, "charter-ack", "claude-desktop-01", {"version": 1})
        files = list(self.layout.events.glob("*.json"))
        self.assertEqual(len(files), 2)

    def test_filename_carries_ulid_and_actor(self) -> None:
        ev = append_event(self.layout, "heartbeat", "gpt desktop 01")
        expected = self.layout.events / f"{ev.id}-gpt-desktop-01.json"
        self.assertTrue(expected.exists())

    def test_roundtrip_preserves_payload(self) -> None:
        append_event(self.layout, "thread-open", "a", {"id": "T1", "title": "Parser"})
        (ev,) = read_events(self.layout)
        self.assertEqual(ev.event, "thread-open")
        self.assertEqual(ev.data["title"], "Parser")

    def test_events_returned_in_chronological_order(self) -> None:
        for i in range(5):
            append_event(self.layout, "heartbeat", f"agent-{i}")
        ids = [e.id for e in read_events(self.layout)]
        self.assertEqual(ids, sorted(ids))

    def test_corrupt_file_is_reported(self) -> None:
        append_event(self.layout, "heartbeat", "a")
        bad = self.layout.events / "01BADFILE-a.json"
        bad.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            read_events(self.layout)

    def test_sanitise_actor_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            sanitise_actor("!!!")

    def test_event_file_is_valid_json(self) -> None:
        ev = append_event(self.layout, "heartbeat", "a")
        raw = json.loads((self.layout.events / f"{ev.id}-a.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["actor"], "a")


if __name__ == "__main__":
    unittest.main()
