#!/usr/bin/env python3
"""TEMPORARY diagnostic (removed before merge): print the table rows around
each reinsurer metric in recent SEC filings, so the parser can be fitted to
the real layouts. Runs only on GitHub's runners (the dev sandbox can't reach
the SEC)."""
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fetch_reinsurer_spreads as rs  # noqa: E402

TARGETS = [
    ("KKR", 1404912, ("8-K",), ("2.02",), r"earningsrelease", [r"insurance operating", r"insurance segment", r"global atlantic"], 1),
    ("F&G", 1934850, ("8-K",), ("2.02",), r"earningsrelease|financialsupp", [r"adjusted net earnings"], 2),
]


def show_tables(html, phrases, max_tables=7):
    shown = 0
    for t in rs.html_tables(html):
        rows = [[txt for txt, _ in r] for r in t["rows"]]
        hit = [i for i, r in enumerate(rows) if r and any(re.search(p, " ".join(r[:3]).lower()) for p in phrases)]
        if not hit:
            continue
        shown += 1
        print(f"      TABLE context={t['context'][-160:]!r}")
        first = hit[0]
        keep = set(range(0, 6)) | set(range(max(0, first - 6), first + 2)) | set(hit[:6])
        for i in sorted(k for k in keep if k < len(rows)):
            print(f"        r{i}: {t['rows'][i]}")
        if shown >= max_tables:
            break
    return shown


def main():
    since = date(2023, 1, 1)
    for label, cik, forms, items, hint, phrases, n in TARGETS:
        company = {"name": label, "cik": cik, "forms": forms, "items": items, "doc_hint": hint}
        print(f"=== {label} (CIK {cik})")
        try:
            filings = rs.list_filings(company, since)
        except Exception as e:
            print(f"  list failed: {e}")
            continue
        print(f"  {len(filings)} filings; newest: {[(f['filed'], f['accession']) for f in filings[-6:]]}")
        picks = filings[-n:] if n else [f for f in filings if f["filed"].startswith(("2023-11", "2024-11"))]
        for f in reversed(picks):
            acc = f["accession"].replace("-", "")
            base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}"
            try:
                idx = rs.sec_json(f"{base}/index.json")
            except Exception as e:
                print(f"  {f['filed']} index failed: {e}")
                continue
            names = [i["name"] for i in idx.get("directory", {}).get("item", [])]
            print(f"  -- {f['filed']} {f['accession']} primary={f['primary']} files={names[:14]}")
            docs = [x for x in names if x.lower().endswith((".htm", ".html")) and "index" not in x.lower() and not x.startswith("R")]
            for name in [x for x in docs if re.search(hint, x, re.I)][:3]:
                html = rs.sec_get(f"{base}/{name}", timeout=60)
                text = rs.plain_text(html).lower()
                found = {p: len(re.findall(p.strip("^"), text)) for p in phrases}
                print(f"    {name}: {len(html)//1024}KB phrase-hits={found}")
                if any(found.values()):
                    for p in phrases:
                        for m in list(re.finditer(p.strip("^"), text))[:2]:
                            print(f"      ...{text[max(0, m.start()-120):m.end()+160]!r}")
                    if not show_tables(html, [p if p.startswith("^") else p for p in phrases]):
                        print("      (no table row starts with the phrase)")
                    if label == "KKR":
                        print(f"      tags: table={html.lower().count('<table')} tr={html.lower().count('<tr')} div={html.lower().count('<div')}")
                        for m in list(re.finditer(r"insurance", text))[:200]:
                            w = text[m.start():m.start() + 140]
                            if re.search(r"\d{2,}", w) and ("operating earnings" in w or "net investment" in w or "segment" in w):
                                print(f"      WIN {w!r}")
                        i = html.lower().find("insurance operating earnings")
                        j = html.lower().find(">insurance<")
                        for k in (i, j):
                            if k >= 0:
                                print(f"      RAW {html[max(0, k-700):k+500]!r}")


if __name__ == "__main__":
    main()
