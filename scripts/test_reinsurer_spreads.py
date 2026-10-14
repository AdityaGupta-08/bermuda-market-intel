#!/usr/bin/env python3
"""Offline checks for the SEC spread-disclosure fetcher (EDGAR is mocked).

Run: python scripts/test_reinsurer_spreads.py
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import fetch_reinsurer_spreads as rs  # noqa: E402

_NET_GUARD = mock.patch("urllib.request.urlopen", side_effect=OSError("network blocked in tests"))


def setUpModule():
    global _urlopen
    _urlopen = _NET_GUARD.start()


def tearDownModule():
    _NET_GUARD.stop()
    if _urlopen.call_count:
        raise AssertionError(f"tests attempted real network access: {_urlopen.call_args_list}")


def table(rows, context=""):
    """rows: list of [(text, colspan), ...] or plain strings (colspan 1)."""
    out = f"<p>{context}</p><table>"
    for r in rows:
        out += "<tr>" + "".join(
            f'<td colspan="{c[1]}">{c[0]}</td>' if isinstance(c, tuple) else f"<td>{c}</td>" for c in r) + "</tr>"
    return out + "</table>"


# Athene supplement: five quarterly trend columns (each header spans "$" and
# the number), then YTD columns that must be ignored.
ATHENE = table([
    ["", ("2Q'24", 2), ("3Q’24", 2), ("4Q'24", 2), ("1Q'25", 2), ("2Q'25", 2), ("YTD'24", 2), ("YTD'25", 2)],
    ["Spread related earnings", "$", "712", "$", "855", "$", "838", "$", "804", "$", "820", "$", "1,528", "$", "1,624"],
    ["Net investment spread", "1.55", "%", "1.66", "%", "1.62", "%", "1.60", "%", "1.62", "%", "1.60", "%", "1.61", "%"],
], context="Spread Related Earnings (In millions, except percentages)")

# KKR-style 10-Q table: two-row header, three- and six-month groups, $ thousands.
KKR = table([
    ["", ("Three Months Ended June 30,", 6), ("Six Months Ended June 30,", 6)],
    ["", ("2026", 3), ("2025", 3), ("2026", 3), ("2025", 3)],
    ["Net Investment Income", "$", "2,950,100", "", "$", "2,700,000", "", "$", "5,800,000", "", "$", "5,300,000", ""],
    ["Insurance Operating Earnings", "$", "301,234", "", "$", "280,100", "", "$", "590,000", "", "$", "540,000", ""],
], context="Insurance ($ in thousands)")

# Brookfield-style press release table with quarter-end dates as headers.
BWS = table([
    ["US$ millions", "September 30, 2025", "September 30, 2024"],
    ["Net income", "608", "65"],
    ["Distributable operating earnings (1)", "427", "370"],
])


class PeriodAndValueTests(unittest.TestCase):
    def test_period_formats(self):
        cases = {"2Q'24": "2024Q2", "3Q’24": "2024Q3", "Q4 2025": "2025Q4", "Q1'26": "2026Q1",
                 "Three Months Ended June 30, 2026": "2026Q2", "September 30, 2025": "2025Q3",
                 "Dec. 31, 2025": "2025Q4", "6/30/2026": "2026Q2"}
        for text, want in cases.items():
            self.assertEqual(rs.parse_period(text), want, text)
        for text in ("Six Months Ended June 30, 2026", "YTD'25", "Year Ended December 31, 2025",
                     "June 15, 2026", "2026", "2Q'25 vs 2Q'24", "Change"):
            self.assertIsNone(rs.parse_period(text), text)

    def test_values(self):
        self.assertEqual(rs.parse_value("$ 1,234.5"), 1234.5)
        self.assertEqual(rs.parse_value("(12)"), -12)
        self.assertEqual(rs.parse_value("1.58%"), 1.58)
        for t in ("—", "–", "n/m", "", "$"):
            self.assertIsNone(rs.parse_value(t), t)


class ExtractionTests(unittest.TestCase):
    def test_athene_trend_table_quarters_only(self):
        found, misses = rs.extract_metrics(ATHENE, rs.COMPANIES[0]["metrics"])
        self.assertEqual(found["earnings"], {"2024Q2": 712, "2024Q3": 855, "2024Q4": 838, "2025Q1": 804, "2025Q2": 820})
        self.assertEqual(found["spread"]["2025Q2"], 1.62)
        self.assertEqual(len(found["spread"]), 5)  # YTD columns ignored
        self.assertEqual(misses, [])

    def test_kkr_two_row_header_in_thousands(self):
        found, _ = rs.extract_metrics(KKR, rs.COMPANIES[1]["metrics"])
        self.assertEqual(found["earnings"], {"2026Q2": 301.23, "2025Q2": 280.1})  # six-month columns skipped

    def test_date_headers_and_footnoted_label(self):
        found, _ = rs.extract_metrics(BWS, rs.COMPANIES[2]["metrics"])
        self.assertEqual(found["earnings"], {"2025Q3": 427, "2024Q3": 370})

    def test_full_width_title_row_does_not_hide_columns(self):
        html = table([
            [("Spread related earnings and change in net investment spread", 6)],
            ["", ("1Q'26", 1), ("2Q'26", 1)],
            ["Spread related earnings", "800", "877"],
        ], context="In millions")
        found, _ = rs.extract_metrics(html, rs.COMPANIES[0]["metrics"])
        self.assertEqual(found["earnings"], {"2026Q1": 800, "2026Q2": 877})

    def test_implausible_values_dropped(self):
        html = table([["", "1Q'26", "2Q'26"], ["Spread related earnings", "800", "877000"]])
        found, _ = rs.extract_metrics(html, rs.COMPANIES[0]["metrics"])
        self.assertEqual(found["earnings"], {"2026Q1": 800})

    def test_row_without_quarter_columns_is_reported(self):
        html = table([["", "Amount"], ["Spread related earnings", "877"]])
        found, misses = rs.extract_metrics(html, rs.COMPANIES[0]["metrics"])
        self.assertEqual(found, {})
        self.assertEqual(misses[0]["metric"], "earnings")
        self.assertIn("877", misses[0]["row"])

    def test_metric_mention_survives_entities_and_tags(self):
        html = "<td>Spread&#160;related <b>earnings</b></td>"
        self.assertTrue(rs.mentions_metric(html, rs.COMPANIES[0]))


class MergeTests(unittest.TestCase):
    F_OLD = {"filed": "2025-05-07", "form": "8-K"}
    F_NEW = {"filed": "2025-08-06", "form": "8-K"}

    def test_newest_filing_wins_and_restatement_is_kept(self):
        store = {}
        rs.merge_points(store, "earnings", "2025Q1", 816, self.F_OLD, "u1")
        rs.merge_points(store, "earnings", "2025Q1", 804, self.F_NEW, "u2")
        self.assertEqual(store["earnings"]["2025Q1"], {"value": 804, "filed": "2025-08-06", "form": "8-K",
                                                       "url": "u2", "revised_from": 816})

    def test_older_filing_never_overwrites(self):
        store = {}
        rs.merge_points(store, "earnings", "2025Q1", 804, self.F_NEW, "u2")
        rs.merge_points(store, "earnings", "2025Q1", 816, self.F_OLD, "u1")
        self.assertEqual(store["earnings"]["2025Q1"]["value"], 804)
        self.assertNotIn("revised_from", store["earnings"]["2025Q1"])

    def test_trim_keeps_recent_quarters(self):
        pts = {"earnings": {f"20{y}Q{q}": {"value": 1} for y in range(20, 26) for q in range(1, 5)}}
        rs.trim(pts, keep=16)
        self.assertEqual(len(pts["earnings"]), 16)
        self.assertEqual(min(pts["earnings"]), "2022Q1")


class EdgarFlowTests(unittest.TestCase):
    """update_company / main against a fake EDGAR."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.object(rs, "OUT", Path(self.tmp.name) / "reinsurer_spreads.json"),
                  mock.patch.object(rs, "REQUEST_GAP", 0),
                  mock.patch.object(rs, "flush_source_health")):
            p.start()
            self.addCleanup(p.stop)
        self.calls = []
        self.submissions = {"filings": {"recent": {
            "form": ["8-K", "8-K", "10-Q", "8-K"],
            "filingDate": ["2026-08-05", "2026-07-01", "2026-08-06", "2020-01-01"],
            "accessionNumber": ["0001527469-26-000060", "0001527469-26-000050", "0001527469-26-000056", "0001527469-20-000001"],
            "primaryDocument": ["ahl-20260805.htm", "ahl-20260701.htm", "ahl-20260630.htm", "old.htm"],
            "items": ["2.02,9.01", "5.07", "", "2.02"],
        }, "files": []}}
        self.docs = {
            "index.json": {"directory": {"item": [{"name": "ahl-20260805.htm"},
                                                  {"name": "athq22026financialsuppleme.htm"}]}},
            "athq22026financialsuppleme.htm": table([
                ["", "2Q'25", "3Q'25", "4Q'25", "1Q'26", "2Q'26"],
                ["Spread related earnings", "820", "872", "850", "719", "877"],
                ["Net investment spread", "1.62%", "1.66%", "1.60%", "1.31%", "1.58%"],
            ], context="(In millions)"),
            "ahl-20260805.htm": "<html>cover page</html>",
        }

    def fake_get(self, url, timeout=30):
        self.calls.append(url)
        if "submissions" in url:
            return json.dumps(self.submissions)
        name = url.rsplit("/", 1)[1]
        body = self.docs[name]
        return json.dumps(body) if isinstance(body, dict) else body

    def test_reads_only_earnings_8ks_in_window_then_runs_incrementally(self):
        athene = rs.COMPANIES[0]
        state = {}
        with mock.patch.object(rs, "sec_get", self.fake_get):
            rs.update_company(athene, state, rs.date(2023, 1, 1))
        self.assertEqual(list(state["processed"]), ["0001527469-26-000060"])  # 5.07 8-K, 10-Q, 2020 filing skipped
        self.assertEqual(state["points"]["earnings"]["2026Q2"]["value"], 877)
        self.assertEqual(state["points"]["spread"]["2026Q1"]["value"], 1.31)
        self.assertTrue(state["points"]["earnings"]["2026Q2"]["url"].endswith("/000152746926000060/athq22026financialsuppleme.htm"))
        self.calls.clear()
        with mock.patch.object(rs, "sec_get", self.fake_get):
            rs.update_company(athene, state, rs.date(2023, 1, 1))
        self.assertEqual(len(self.calls), 1)  # just the submissions list

    def test_spent_time_budget_leaves_filings_for_the_next_run(self):
        athene, state = rs.COMPANIES[0], {}
        with mock.patch.object(rs, "sec_get", self.fake_get):
            rs.update_company(athene, state, rs.date(2023, 1, 1), deadline=rs.time.monotonic() - 1)
        self.assertEqual(state["processed"], {})  # nothing marked read
        with mock.patch.object(rs, "sec_get", self.fake_get):
            rs.update_company(athene, state, rs.date(2023, 1, 1), deadline=rs.time.monotonic() + 60)
        self.assertEqual(state["points"]["earnings"]["2026Q2"]["value"], 877)

    def test_main_writes_output_and_keeps_cache_on_error(self):
        def get(url, timeout=30):
            if "CIK0001527469" in url or "1527469/" in url:
                return self.fake_get(url, timeout)
            raise RuntimeError("SEC refused the request (403)")
        with mock.patch.object(rs, "sec_get", get):
            rs.main()
        out = json.loads(rs.OUT.read_text())
        by = {c["key"]: c for c in out["companies"]}
        self.assertEqual(by["athene"]["status"], "ok")
        self.assertEqual([p["quarter"] for p in by["athene"]["metrics"]["earnings"]["points"]][-1], "2026Q2")
        self.assertEqual(by["global_atlantic"]["status"], "error")
        self.assertIn("403", by["global_atlantic"]["note"])
        self.assertTrue(any(n["name"] == "Prismic Re" for n in out["not_covered"]))
        # A later failing run keeps what was already collected.
        with mock.patch.object(rs, "sec_get", mock.Mock(side_effect=RuntimeError("down"))):
            rs.main()
        again = {c["key"]: c for c in json.loads(rs.OUT.read_text())["companies"]}
        self.assertEqual(again["athene"]["metrics"]["earnings"]["points"][-1]["value"], 877)
        self.assertEqual(again["athene"]["status"], "ok")


if __name__ == "__main__":
    unittest.main(verbosity=2)
