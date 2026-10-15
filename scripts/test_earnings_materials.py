#!/usr/bin/env python3
"""Checks for reading figures out of earnings-call transcripts and releases.

Run: python scripts/test_earnings_materials.py
"""
import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import earnings_materials as em  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

SRE = {"unit": "usd_m", "bounds": (100, 5000), "prose": [r"spread[- ]related earnings", r"\bSRE\b"]}
SPREAD = {"unit": "pct", "bounds": (0.2, 5.0), "prose": [r"net investment spread", r"\bnet spread\b"]}
DOE = {"unit": "usd_m", "bounds": (20, 5000), "prose": [r"distributable operating earnings", r"\bDOE\b"]}
ATHENE = {"earnings": SRE, "spread": SPREAD}

# Synthetic call excerpt: the reported figures plus the usual traps (prior
# year, guidance, another quarter, a change rather than a level, an
# adjusted figure).
CALL = """Sample Holdings (SMPL) Q2 2026 Earnings Call 04-Aug-2026 Corrected Transcript.
Good morning. Retirement Services reported record spread related earnings, or SRE, of $877 million, up 11% year-over-year.
Last year, SRE was $790 million. For the full year 2026 we continue to expect SRE growth of 10%.
Net investment spread declined 11 basis points to 1.47%. In the first quarter, SRE was $835 million.
SRE of $877 million included alternative returns of 9%, which equates to $76 million of lower SRE.
The net investment spread was 147 basis points, compared to 158 basis points a year ago.
Excluding notable items, SRE would have been $905 million. In 2025, SRE was $3.2 billion."""

RELEASE = """Sample Wealth Solutions Reports Second Quarter 2026 Results.
Distributable operating earnings ("DOE") of $488 million for the quarter, compared to $398 million in the prior year period.
DOE for the six months ended June 30, 2026 was $926 million. Net income was $149 million."""


class QuarterTests(unittest.TestCase):
    def test_from_file_names_and_urls(self):
        cases = {
            "APO+2Q26+Transcript.pdf": "2026Q2",
            "KKR_Q2%2726_Earnings_Release.pdf": "2026Q2",
            "https://x.com/files/IR/2026/q2/2026-q2-bws-press-release.pdf": "2026Q2",
            "20260804-2q-2026-apollo-global-management-inc-earnings-conference": "2026Q2",
            "Q4-2025-results.pdf": "2025Q4",
        }
        for name, want in cases.items():
            self.assertEqual(em.quarter_from_name(name), want, name)
        for name in ("20260209-4q-and-full-year-2025-apollo", "report.pdf", "Form10Q.pdf"):
            self.assertIsNone(em.quarter_from_name(name), name)

    def test_from_opening_text(self):
        self.assertEqual(em.quarter_from_text(CALL), "2026Q2")
        self.assertEqual(em.quarter_from_text(RELEASE), "2026Q2")
        self.assertEqual(em.quarter_from_text("Fourth Quarter, 2025 results. Compared with Q3 2025..."), "2025Q4")
        self.assertIsNone(em.quarter_from_text("Annual meeting of shareholders"))


class ProseExtractionTests(unittest.TestCase):
    def test_call_figures_and_traps(self):
        found, notes = em.extract_prose_metrics(CALL, "2026Q2", ATHENE)
        self.assertEqual(found, {"earnings": 877.0, "spread": 1.47})
        self.assertEqual(notes, {})

    def test_release_figure_not_the_comparator_or_six_months(self):
        found, _ = em.extract_prose_metrics(RELEASE, "2026Q2", {"earnings": DOE})
        self.assertEqual(found, {"earnings": 488.0})

    def test_billions_scaled_to_millions(self):
        found, _ = em.extract_prose_metrics("In the second quarter, SRE was $1.1 billion.", "2026Q2", ATHENE)
        self.assertEqual(found, {"earnings": 1100.0})

    def test_change_without_level_is_not_a_figure(self):
        found, _ = em.extract_prose_metrics("SRE increased $87 million on higher volumes.", "2026Q2", ATHENE)
        self.assertEqual(found, {})

    def test_other_quarter_or_year_sentences_skipped(self):
        text = "In the first quarter, SRE was $835 million. In 2Q 2025, SRE was $790 million."
        self.assertEqual(em.extract_prose_metrics(text, "2026Q2", ATHENE)[0], {})

    def test_each_trap_alone_yields_nothing(self):
        # One at a time, so majority voting can't hide a guard that stopped working.
        for text in ("Last year, SRE was $790 million.",                               # comparison before the label
                     "SRE compared to $790 million in the prior year quarter was a record.",  # comparator figure
                     "For the full year, SRE was $3.4 billion.",                         # full-year sentence
                     "We expect SRE of $950 million next quarter.",                     # guidance
                     "Excluding notable items, SRE would have been $905 million.",      # adjusted figure
                     "In 2025, SRE was $3.2 billion.",                                   # another year
                     "Net investment spread declined 11 basis points."):                # change, no level
            self.assertEqual(em.extract_prose_metrics(text, "2026Q2", ATHENE)[0], {}, text)

    def test_disagreeing_sentences_give_nothing(self):
        text = "SRE was $877 million. SRE came in at $880 million."
        found, notes = em.extract_prose_metrics(text, "2026Q2", ATHENE)
        self.assertEqual(found, {})
        self.assertIn("ambiguous", notes["earnings"])

    def test_majority_wins_over_a_stray_mention(self):
        text = "SRE was $877 million. SRE of $877 million was a record. SRE came in at $880 million."
        self.assertEqual(em.extract_prose_metrics(text, "2026Q2", ATHENE)[0], {"earnings": 877.0})

    def test_out_of_bounds_ignored(self):
        text = "SRE impact of $76 million. Net investment spread of 11%."
        self.assertEqual(em.extract_prose_metrics(text, "2026Q2", ATHENE)[0], {})

    def test_decimal_points_do_not_split_sentences(self):
        self.assertEqual(em.sentences("SRE was $1.2 billion. Net spread was 1.47%. Done."),
                         ["SRE was $1.2 billion.", "Net spread was 1.47%.", "Done."])


class DocumentTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "pypdf not installed")
    def test_pdf_transcript_end_to_end(self):
        text = em.pdf_text((FIXTURES / "sample_transcript.pdf").read_bytes())
        self.assertEqual(em.quarter_from_text(em.normalise(text)), "2026Q2")
        self.assertEqual(em.extract_prose_metrics(text, "2026Q2", ATHENE)[0], {"earnings": 877.0, "spread": 1.47})

    def test_html_text_drops_scripts_and_entities(self):
        self.assertEqual(" ".join(em.html_text("<p>SRE&nbsp;of <b>$877</b> million</p><script>x=1</script>").split()),
                         "SRE of $877 million")

    def test_discover_links(self):
        html = ('<a href="/_assets/a/db/1/webcast_transcript/APO+2Q26+Transcript.pdf">T</a>'
                '<a href="https://ir.example.com/_assets/a/db/1/webcast_transcript/APO+2Q26+Transcript.pdf">dup</a>'
                "<a href='/news-events/events/detail/20260505-1q-2026-earnings'>E</a>"
                '<a href="/financials/10-q.pdf">10-Q</a>')
        self.assertEqual(em.discover_links(html, "https://ir.example.com/", r"transcript[^\"']*\.pdf"),
                         ["https://ir.example.com/_assets/a/db/1/webcast_transcript/APO+2Q26+Transcript.pdf"])
        self.assertEqual(em.discover_links(html, "https://ir.example.com/", r"/events/detail/"),
                         ["https://ir.example.com/news-events/events/detail/20260505-1q-2026-earnings"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
