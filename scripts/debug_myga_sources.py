#!/usr/bin/env python3
"""TEMPORARY diagnostic (removed before merge): shape of My Annuity Store's
full-market rate rows endpoint, and whether robots.txt allows it."""
import json
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetchlib import HDR  # noqa: E402

REST = "https://myannuitystore.com/wp-json/mas/v1/rate-rows"


def get(url):
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.status, dict(r.headers), r.read().decode("utf-8", errors="replace")


def text(h):
    return " ".join(re.sub(r"<[^>]+>", " ", h).split())


_, _, robots = get("https://myannuitystore.com/robots.txt")
print("ROBOTS:\n" + robots[:1500])

status, headers, body = get(REST)
print(f"REST status {status} bytes {len(body)} type {headers.get('Content-Type')}")
d = json.loads(body)
print("keys:", {k: (type(v).__name__, len(v) if hasattr(v, '__len__') else v) for k, v in d.items()})
html = d.get("html") or ""
rows = re.findall(r"<tr\b([^>]*)>(.*?)</tr>", html, re.S | re.I)
print(f"rows {len(rows)}")
attr_names = Counter(n for a, _ in rows for n in re.findall(r"\b(data-[a-z-]+)=", a))
print("row data-attrs:", attr_names.most_common())
cell_classes = Counter(c for _, r in rows for c in re.findall(r"<td[^>]*class=\"([^\"]+)\"", r))
print("cell classes:", cell_classes.most_common(20))
span_classes = Counter(c for _, r in rows for c in re.findall(r"<span[^>]*class=\"([^\"]+)\"", r))
print("span classes:", span_classes.most_common(30))
for i in (0, 1, 2, len(rows) // 2, len(rows) - 1):
    a, r = rows[i]
    print(f"\nROW {i} attrs={' '.join(a.split())[:600]!r}")
    print("  cells:", [text(c)[:70] for c in re.findall(r"<td\b[^>]*>(.*?)</td>", r, re.S)])
    if i == 0:
        print("  raw:", " ".join(r.split())[:2500])

terms = Counter(re.search(r'data-term="([^"]*)"', a).group(1) if 'data-term="' in a else "?" for a, _ in rows)
ratings = Counter(re.search(r'data-rating="([^"]*)"', a).group(1) if 'data-rating="' in a else "?" for a, _ in rows)
print("\nterms:", sorted(terms.items(), key=lambda kv: (len(kv[0]), kv[0])))
print("ratings:", ratings.most_common())
si = [text(r)[:90] for _, r in rows if re.search(r"simple", r, re.I)]
print(f"simple-interest rows {len(si)}: {si[:6]}")
names = Counter()
for _, r in rows:
    co = re.search(r'class="mrt-td-co">(.*?)</span>', r)
    pr = re.search(r'class="mrt-td-pr">(.*?)</span>', r)
    term = re.search(r'mrt-td-term">(.*?)</td>', r)
    names[(text(co.group(1)) if co else "", text(pr.group(1)) if pr else "", text(term.group(1)) if term else "")] += 1
dups = [(k, n) for k, n in names.items() if n > 1]
print(f"distinct (co, product, term) {len(names)}; repeated {len(dups)}: {dups[:8]}")
ca = [k for k in names if re.search(r"\bCA\b|\bNY\b", k[1])]
print(f"state-variant names {len(ca)}: {ca[:8]}")
states = Counter(len(re.search(r'data-states="([^"]*)"', a).group(1).split(",")) if 'data-states="' in a else -1 for a, _ in rows)
print("states-per-row histogram:", sorted(states.items())[:40])
fl = sum(1 for a, _ in rows if re.search(r'data-states="[^"]*\bFL\b', a))
print(f"rows available in FL: {fl}")
