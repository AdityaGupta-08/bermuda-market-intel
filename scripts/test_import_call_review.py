#!/usr/bin/env python3
"""Checks for the earnings-call review importer.

Run: python scripts/test_import_call_review.py
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import import_call_review as icr  # noqa: E402


def para(text, heading=None):
    h = f" heading='{heading}'" if heading else ""
    return f"<paragraph{h}>{text}</paragraph>"


def t(s):
    return f"<text>{s}</text>"


def link(label, href):
    return f"<text><link href='{href}'>{label}</link></text>"


def items(*lines):
    return "<list kind='bullet'>" + "".join(f"<listItem><paragraph>{t(x)}</paragraph></listItem>" for x in lines) + "</list>"


# Same structure as the routine's doc, two companies, one or two calls each.
XML = "<doc>" + "".join([
    para(t("PE Life Reinsurers — Earnings Call Review FY2023–2026"), 1),
    "<paragraph><text>As of </text><date value='2026-10-12'/><text> · </text><mention name='AG'/></paragraph>",
    para(t("Executive summary"), 2),
    para(t("As of 12 Oct 2026 the latest calls covered are…")),
    items("Tone has drifted down for four of five.", "Spread compression is the common thread."),
    para(t("1. Athene / Apollo — Retirement Services (metric: Spread Related Earnings, SRE)"), 2),
    para(t("Coverage: Q1 FY2023 to Q2 FY2026 (latest call 4 Aug 2026).")),
    para(t("Q1 FY2026 — 6 May 2026 — ") + link("Apollo IR transcript", "https://ir.example/q1.pdf") + t(" — transcript read"), 3),
    items("🔴 Bad [SRE] SRE $719M (would be $907M at 11% alts).",
          "🟢 Good [Guidance] 10% SRE growth reaffirmed.",
          "🟡 Average [Competition] Competition called irrational."),
    para(t("Meter: G1 / B1 / N3 → 0.00 (Average), ↓ (spread 97bp, alts miss). (Count corrected from the research notes.)")),
    para(t("Q2 FY2026 — 4 Aug 2026 — ") + link("Apollo IR transcript", "https://ir.example/q2.pdf") + t(", ")
         + link("8-K release", "https://sec.example/r.htm") + t(" — transcript and release read"), 3),
    items("🟢 Good [SRE] Record SRE $877M ($1.41/sh).", "🟡 Average [Spread] 114bp (Q1 97bp)."),
    para(t("Meter: G1 / B0 / N2 → +0.50 (Good), ↑ (record SRE). Not discussed: Bermuda tax.")),
    para(t("5. F&amp;G Annuities &amp; Life (metric: adjusted net earnings, ANE)"), 2),
    para(t("Q2 FY2026 — 6 Aug 2026 — ") + link("EarningsWhispers", "https://ew.example") + t(" — AI summary of transcript"), 3),
    items("🔴 Bad [Earnings] ANE $85M ($0.65/sh) vs $103M."),
    para(t("Meter: G0 / B1 / N1 → −1.00 (Bad), ↓.")),
    para(t("Cross-company theme matrix"), 2),
    "<table><row><cell><paragraph>" + t("Theme") + "</paragraph></cell></row></table>",
    para(t("Watch list for the Q3 2026 calls"), 2),
    items("Athene / Apollo: whether net spread returns to the 120–125bp guide.", "F&amp;G: Q3 call on 6 Nov 2026."),
    para(t("Sources"), 2),
    items("Apollo: transcripts."),
]) + "</doc>"


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.doc = icr.parse_review(XML)

    def test_header_and_summary(self):
        self.assertEqual(self.doc["title"], "PE Life Reinsurers — Earnings Call Review FY2023–2026")
        self.assertEqual(self.doc["as_of"], "2026-10-12")
        self.assertEqual(self.doc["summary"], ["Tone has drifted down for four of five.", "Spread compression is the common thread."])

    def test_companies_mapped_to_page_keys(self):
        self.assertEqual(list(self.doc["companies"]), ["athene", "fg"])
        self.assertEqual(self.doc["companies"]["athene"]["metric"], "Spread Related Earnings, SRE")
        self.assertTrue(self.doc["companies"]["athene"]["coverage"].startswith("Q1 FY2023 to Q2 FY2026"))

    def test_call_heading_lines_and_meter(self):
        q2 = self.doc["companies"]["athene"]["quarters"]["2026Q2"]
        self.assertEqual(q2["date"], "4 Aug 2026")
        self.assertEqual(q2["read"], "transcript and release read")
        self.assertEqual([s["label"] for s in q2["sources"]], ["Apollo IR transcript", "8-K release"])
        self.assertEqual(q2["lines"][0], {"tone": "good", "theme": "SRE", "text": "Record SRE $877M ($1.41/sh)."})
        self.assertEqual(q2["meter"]["score"], 0.5)
        self.assertEqual((q2["meter"]["label"], q2["meter"]["arrow"]), ("Good", "↑"))
        self.assertEqual(q2["meter"]["note"], "(record SRE). Not discussed: Bermuda tax")
        q1 = self.doc["companies"]["athene"]["quarters"]["2026Q1"]
        self.assertEqual([l["tone"] for l in q1["lines"]], ["bad", "good", "average"])
        self.assertEqual(q1["meter"]["note"], "(spread 97bp, alts miss)")  # bookkeeping aside dropped

    def test_unicode_minus_and_ampersand_company(self):
        fg = self.doc["companies"]["fg"]["quarters"]["2026Q2"]
        self.assertEqual(fg["meter"]["score"], -1.0)
        self.assertEqual(fg["read"], "AI summary of transcript")

    def test_watch_list_attached_and_matrix_ignored(self):
        self.assertTrue(self.doc["companies"]["athene"]["watch"].startswith("whether net spread"))
        self.assertEqual(self.doc["companies"]["fg"]["watch"], "Q3 call on 6 Nov 2026.")

    def test_main_writes_and_refuses_empty(self):
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d) / "export.json", Path(d) / "out.json"
            src.write_text(json.dumps({"data": {"xml": XML}}))
            icr.main([str(src), "--url", "https://claude.ai/artifact/x", "--out", str(out)])
            written = json.loads(out.read_text())
            self.assertEqual(written["source"]["url"], "https://claude.ai/artifact/x")
            self.assertEqual(len(written["companies"]["athene"]["quarters"]), 2)
            src.write_text("<doc><paragraph heading='1'><text>Empty</text></paragraph></doc>")
            with self.assertRaises(SystemExit):
                icr.main([str(src), "--out", str(out)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
