#!/usr/bin/env python3
"""TEMPORARY diagnostic (removed before merge): table layout of the My Annuity
Store rate pages, so the MYGA fetcher can parse them."""
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetchlib import HDR  # noqa: E402

PAGES = [
    "https://myannuitystore.com/annuity-rates/marketplace/",
    "https://myannuitystore.com/annuity-rates/fixed-annuity-rates/",
    "https://myannuitystore.com/annuity-rates/fixed-annuity-rates/5-year/",
]


def get(url):
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", errors="replace")


def text(h):
    return " ".join(re.sub(r"<[^>]+>", " ", h).split())


for url in PAGES:
    print(f"\n=== {url}")
    try:
        html = get(url)
    except Exception as e:
        print(f"  ERROR {e}")
        continue
    for ti, tbl in enumerate(re.findall(r"<table\b(.*?)</table>", html, re.S | re.I)):
        attrs = re.match(r"([^>]*)>", tbl).group(1)[:200]
        rows = re.findall(r"<tr\b([^>]*)>(.*?)</tr>", tbl, re.S | re.I)
        print(f"  TABLE {ti} attrs={attrs!r} rows={len(rows)}")
        for ri, (rattrs, r) in enumerate(rows[:6] + rows[-2:]):
            cells = re.findall(r"<t([hd])\b([^>]*)>(.*?)</t[hd]>", r, re.S | re.I)
            print(f"    r{ri} rowattrs={rattrs[:160]!r}")
            print(f"       cells={[ (k, text(c)[:60]) for k, a, c in cells]}")
            if ri == 1:
                print(f"       raw={r[:1200]!r}")
    for pat in (r"Showing[^<]{0,80}", r"of \d+ (?:products|results|annuities)", r"Load more", r"data-page", r"page/2", r"\?pg=", r"Rates updated[^<]{0,80}"):
        hits = re.findall(pat, html, re.I)[:3]
        if hits:
            print(f"  {pat}: {hits}")
