"""``decision ratify`` drafts an ADR in CHARTER.md and bumps its version."""

from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from agentmgr.charter import charter_fingerprint
from agentmgr.cli import main
from agentmgr.paths import Layout
from agentmgr.scaffold import init_project


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class AdrDraftTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._cwd = os.getcwd()
        os.chdir(self.root)
        self.layout = init_project(self.root, project_name="demo")

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def charter(self) -> str:
        return self.layout.charter.read_text(encoding="utf-8")

    def decide(self, did: str, title: str, body: str = "") -> tuple[int, str, str]:
        args = ["decision", "propose", "--as", "a", "--id", did, "--title", title]
        if body:
            args += ["--body", body]
        self.cli(*args)
        return self.cli("decision", "ratify", did, "--as", "mgr")

    def test_first_ratified_decision_replaces_the_template_adr(self) -> None:
        rc, out, _ = self.decide("D1", "DELETE rotasi ekle", "Sepetten urun cikarilamiyor.")
        text = self.charter()

        self.assertEqual(rc, 0)
        self.assertIn("### ADR-001: DELETE rotasi ekle", text)
        self.assertNotIn("_<başlık>_", text)
        self.assertEqual(text.count("### ADR-"), 1)
        self.assertIn("- **Bağlam:** Sepetten urun cikarilamiyor.", text)
        self.assertIn("(`decision ratify D1`, mgr)", text)
        self.assertIn("ADR-001 drafted in CHARTER.md (now v2)", out)

    def test_version_and_date_are_bumped(self) -> None:
        self.decide("D1", "Bir karar")
        text = self.charter()
        self.assertEqual(charter_fingerprint(self.layout)[0], 2)
        self.assertIn(f"**Son güncelleme:** _{today()}_", text)

    def test_next_decision_gets_the_next_number_and_keeps_earlier_adrs(self) -> None:
        self.decide("D1", "Ilk karar")
        self.decide("D2", "Ikinci karar")
        text = self.charter()

        self.assertIn("### ADR-001: Ilk karar", text)
        self.assertIn("### ADR-002: Ikinci karar", text)
        self.assertLess(text.index("ADR-001"), text.index("ADR-002"))
        self.assertEqual(charter_fingerprint(self.layout)[0], 3)

    def test_missing_body_leaves_a_placeholder_to_fill(self) -> None:
        self.decide("D1", "Govdesiz karar")
        self.assertIn("**Bağlam:** _<neden bir karara ihtiyaç vardı>_", self.charter())
        self.assertIn("**Sonuç:** _<etkileri ve ödünleşimleri yaz>_", self.charter())

    def test_multiline_body_is_indented_under_the_bullet(self) -> None:
        self.decide("D1", "Cok satirli", "birinci satir\nikinci satir")
        self.assertIn("- **Bağlam:** birinci satir\n  ikinci satir\n- **Karar:**", self.charter())

    def test_charter_that_already_mentions_the_decision_is_left_alone(self) -> None:
        with open(self.layout.charter, "a", encoding="utf-8") as fh:
            fh.write("\n### ADR-009: elle yazilmis (D1)\n")
        before = self.charter()
        rc, out, _ = self.decide("D1", "Zaten kayitli")

        self.assertEqual(rc, 0)
        self.assertEqual(self.charter(), before)
        self.assertIn("already mentions this decision", out)

    def test_similar_id_is_not_mistaken_for_a_mention(self) -> None:
        with open(self.layout.charter, "a", encoding="utf-8") as fh:
            fh.write("\n### ADR-009: baska karar (D12)\n")
        rc, out, _ = self.decide("D1", "Gercekten yeni")
        text = self.charter()
        self.assertNotIn("already mentions", out)
        self.assertIn("### ADR-001: Gercekten yeni", text)  # took the empty template slot
        self.assertIn("### ADR-009: baska karar (D12)", text)

    def test_no_adr_flag_leaves_the_charter_untouched(self) -> None:
        before = self.charter()
        self.cli("decision", "propose", "--as", "a", "--id", "D1", "--title", "x")
        rc, out, _ = self.cli("decision", "ratify", "D1", "--as", "mgr", "--no-adr")
        self.assertEqual(rc, 0)
        self.assertEqual(self.charter(), before)
        self.assertIn("record it in CHARTER.md section 9", out)

    def test_ratifying_twice_does_not_write_a_second_adr(self) -> None:
        self.decide("D1", "Bir kez")
        once = self.charter()
        self.cli("decision", "ratify", "D1", "--as", "mgr")
        self.assertEqual(self.charter(), once)

    def test_missing_charter_does_not_fail_the_ratify(self) -> None:
        self.cli("decision", "propose", "--as", "a", "--id", "D1", "--title", "x")
        self.layout.charter.unlink()
        rc, out, _ = self.cli("decision", "ratify", "D1", "--as", "mgr")
        self.assertEqual(rc, 0)
        self.assertIn("no CHARTER.md found", out)

    def test_crlf_charter_keeps_its_line_endings(self) -> None:
        raw = self.layout.charter.read_bytes().decode("utf-8").replace("\r\n", "\n")
        self.layout.charter.write_bytes(raw.replace("\n", "\r\n").encode("utf-8"))
        self.decide("D1", "Windows satir sonu")

        data = self.layout.charter.read_bytes()
        self.assertIn(b"### ADR-001: Windows satir sonu", data)
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))

    def test_agents_that_acked_the_old_charter_show_up_as_drifted(self) -> None:
        self.cli("charter-ack", "gpt-01")
        self.decide("D1", "Charter degisti")
        _, out, _ = self.cli("reconcile")
        self.assertIn("charter drift: gpt-01", out)

    def test_adr_is_appended_after_a_handwritten_one(self) -> None:
        text = self.charter()
        start = text.index("### ADR-001")
        self.layout.charter.write_text(
            text[:start]
            + "### ADR-004: elle yazilmis\n\n- **Karar:** ornek\n\n### ADR-005: ikinci elle\n\n- **Karar:** ornek\n",
            encoding="utf-8",
        )
        self.decide("D1", "Sonraki")
        text = self.charter()
        self.assertIn("### ADR-006: Sonraki", text)
        self.assertLess(text.index("ADR-005"), text.index("ADR-006"))
        self.assertIn("### ADR-004: elle yazilmis", text)


if __name__ == "__main__":
    unittest.main()
