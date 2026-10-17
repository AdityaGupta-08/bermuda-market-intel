#!/usr/bin/env python3
"""TEMPORARY diagnostic (removed before merge): how My Annuity Store's
marketplace loads the full market behind the server-rendered top 25."""
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetchlib import HDR  # noqa: E402

PAGE = "https://myannuitystore.com/annuity-rates/marketplace/"
PATTERNS = r"admin-ajax|wp-json|fetch\(|XMLHttpRequest|\$\.(?:ajax|post|get)|action\s*[:=]|nonce|loadFull|load_full|fullMarket|full_market|mrtLoad|mrt_load|\.json"


def get(url):
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", errors="replace")


def snippets(src, label, limit=25):
    seen = 0
    for m in re.finditer(PATTERNS, src, re.I):
        a, b = max(0, m.start() - 220), m.end() + 320
        print(f"  [{label}] …{' '.join(src[a:b].split())}…")
        seen += 1
        if seen >= limit:
            break


html = get(PAGE)
print(f"page bytes {len(html)}")
for m in re.finditer(r"Load the full market", html):
    print("  BUTTON:", " ".join(html[max(0, m.start() - 900):m.end() + 600].split()))
    break
for m in re.finditer(r"<(?:div|section|form)[^>]*\bmrt[^>]*>", html):
    print("  CONTAINER:", m.group(0)[:400])
srcs = re.findall(r"<script[^>]+src=[\"']([^\"']+)", html)
print("SCRIPTS:", srcs)
for i, body in enumerate(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I)):
    if re.search(r"mrt|market|rates", body, re.I) and len(body) > 40:
        print(f"INLINE {i} len={len(body)} head={' '.join(body[:300].split())!r}")
        snippets(body, f"inline{i}")
for s in srcs:
    url = urllib.parse.urljoin(PAGE, s)
    if "myannuitystore.com" not in url or not re.search(r"mrt|market|rate|theme|main|app|custom", url, re.I):
        continue
    try:
        js = get(url)
    except Exception as e:
        print(f"  {url}: ERROR {e}")
        continue
    print(f"EXTERNAL {url} len={len(js)}")
    snippets(js, url.rsplit('/', 1)[-1][:40])
