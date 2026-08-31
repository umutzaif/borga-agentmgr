import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agentmgr.events import append_event
from agentmgr.ledger import GENESIS, chain, head, rebuild, verify
from agentmgr.paths import Layout


class LedgerChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.layout = Layout(Path(self._tmp.name))
        self.layout.base.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _seed(self, n: int = 3) -> None:
        for i in range(n):
            append_event(self.layout, "heartbeat", f"agent-{i}")

    def test_empty_head_is_genesis(self) -> None:
        self.assertEqual(head(self.layout), GENESIS)

    def test_chain_links_prev_to_previous_hash(self) -> None:
        self._seed(3)
        rows = chain(_read(self.layout))
        self.assertEqual(rows[0]["prev"], GENESIS)
        self.assertEqual(rows[1]["prev"], rows[0]["hash"])
        self.assertEqual(rows[2]["prev"], rows[1]["hash"])

    def test_rebuild_is_deterministic(self) -> None:
        self._seed(4)
        first = rebuild(self.layout)
        second = rebuild(self.layout)
        self.assertEqual([r["hash"] for r in first], [r["hash"] for r in second])

    def test_verify_passes_on_clean_ledger(self) -> None:
        self._seed(3)
        rebuild(self.layout)
        ok, msg = verify(self.layout)
        self.assertTrue(ok, msg)

    def test_verify_detects_edited_ledger_row(self) -> None:
        self._seed(3)
        rebuild(self.layout)
        lines = self.layout.ledger.read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[1])
        row["actor"] = "tampered"
        lines[1] = json.dumps(row, sort_keys=True, separators=(",", ":"))
        self.layout.ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok, msg = verify(self.layout)
        self.assertFalse(ok)

    def test_verify_detects_added_event_file(self) -> None:
        self._seed(2)
        rebuild(self.layout)
        append_event(self.layout, "heartbeat", "sneaky")  # ledger now stale
        ok, _ = verify(self.layout)
        self.assertFalse(ok)


def _read(layout: Layout):
    from agentmgr.events import read_events

    return read_events(layout)


if __name__ == "__main__":
    unittest.main()
