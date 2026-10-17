#!/usr/bin/env python3
"""TEMPORARY diagnostic (removed before merge): what MYGA quote pages return to
a plain HTTP client, so the MYGA fetcher can be pointed at one that works."""
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetchlib import HDR  # noqa: E402
import fetch_myga as fm  # noqa: E402

PAGES = [
    "https://www.stantheannuityman.com/myga-quote?state=FL&years=5",
    "https://myannuitystore.com/myga/",
    "https://myannuitystore.com/annuities/fixed-annuity/myga/",
    "https://myannuitystore.com/annuity-rates/marketplace/",
]
ROBOTS = ["https://www.stantheannuityman.com/robots.txt", "https://myannuitystore.com/robots.txt"]


def get(url):
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.status, r.headers.get("content-type"), r.read().decode("utf-8", errors="replace")


def text(html):
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


for url in ROBOTS:
    try:
        _, _, body = get(url)
        print(f"=== {url}\n" + "\n".join(l for l in body.splitlines() if l.strip())[:1500])
    except Exception as e:
        print(f"=== {url}: {e}")

for url in PAGES:
    print(f"\n=== {url}")
    try:
        status, ctype, html = get(url)
    except Exception as e:
        print(f"  ERROR {e}")
        continue
    t = text(html)
    print(f"  status={status} type={ctype} html={len(html)//1024}KB text={len(t)//1024}KB "
          f"tables={html.lower().count('<table')} tr={html.lower().count('<tr')}")
    n_rat = len(re.findall(r"(?<![A-Za-z])A[+-]{0,2}(?![A-Za-z])", t))
    n_pct = len(re.findall(r"\d\.\d{2}\s*%", t))
    print(f"  ratings in text: {n_rat}  pct: {n_pct}")
    blobs = fm.extract_json_blobs(html)
    print(f"  json blobs: {len(blobs)}; harvested quotes from blobs: {sum(len(fm.harvest_quotes(b, 5)) for b in blobs)}")
    print(f"  html-table quotes (fetcher's fallback): {len(fm.parse_html_table(html, 5))}")
    apis = sorted(set(re.findall(r"""["'](https?://[^"']*(?:api|wp-json|graphql|quote|rates?)[^"']*)["']""", html, re.I)))[:25]
    print(f"  api-ish urls: {apis}")
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)[:15]
    print(f"  script srcs: {srcs}")
    for m in list(re.finditer(r"(\d+)[- ]?(?:Year|Yr)[^%]{0,160}?\d\.\d{2}\s*%[^%]{0,120}", t, re.I))[:12]:
        print(f"  ROW? {m.group(0)[:300]!r}")
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I)[:8]:
        print(f"  TR {text(tr)[:250]!r}")
    i = t.lower().find("guaranteed apy")
    if i >= 0:
        print(f"  APY CONTEXT {t[max(0, i-400):i+900]!r}")
