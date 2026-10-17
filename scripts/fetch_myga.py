#!/usr/bin/env python3
"""MYGA new-money spreads over Treasuries, bucketed by AM Best rating.

Feeds the annuity in-the-money meter. The calculator needs one number — the
spread a policyholder can actually reinvest at, over the matched-maturity
Treasury — and until now that spread was a hardcoded calibration constant.
This turns it into an observed market statistic.

SOURCE
------
My Annuity Store's rate marketplace (rates from AnnuityRateWatch, updated
daily). The page server-renders only the 25 highest rates; its "Show all
products" button pulls the full market — every MYGA, one table row each —
from a public JSON endpoint, and this reads that same endpoint. Each row
carries its terms as data attributes: guarantee term, AM Best rating, the
states it is sold in, premium bands with the rate for each, and whether the
rate is simple interest.

The top-25 slice is never used as a fallback: it is the top of the market by
construction, so its "median" would overstate every bucket. Fewer than
MIN_MARKET_ROWS rows means something changed, and the fetcher reports stale
rather than publish a skewed spread.

FROM ROWS TO QUOTES
-------------------
- Only products sold in STATE that take a PREMIUM deposit, at the rate that
  deposit earns (banded products pay more on larger deposits).
- Simple-interest rates are converted to the compound annual yield with the
  same maturity value; 7.00% simple over 5 years is about 6.19% compounded.
  Comparing them at face value would flatter those products by 50-90bp.
- One quote per carrier and term, the carrier's best: the median then
  describes the typical carrier, not whichever carrier files the most
  product variants (rider, MVA and state versions of one contract).

WHAT IS STORED, AND WHY IT IS ONLY THIS
---------------------------------------
Carrier names and individual quotes are NEVER written to disk. The output
schema has no field for them. What is stored is, per rating bucket and term:
the median and top-quartile SPREAD OVER THE MATCHED TREASURY, and a count.

That is a deliberate constraint, not an oversight. This repository deploys
publicly to GitHub Pages, so persisting a third party's compiled carrier-level
rate table would be republishing their work product. A distribution statistic
derived against a Treasury benchmark is a different thing, and it happens to
be exactly — and only — what the model consumes.

POLITENESS
----------
The pipeline runs every three hours; MYGA rates move on carrier pricing
committees, not intraday. This fetcher makes one request, and no-ops unless
the existing file is older than MIN_REFRESH_HOURS. Set MYGA_FETCH=off to
disable it entirely.

Self-test (no network):  python scripts/fetch_myga.py --selftest
"""
import argparse
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from html import unescape
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetchlib import DATA, HDR, record_source, flush_source_health  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("fetch")

OUT = DATA / "myga_spreads.json"
PAGE_URL = "https://myannuitystore.com/annuity-rates/marketplace/"
MARKET_URL = "https://myannuitystore.com/wp-json/mas/v1/rate-rows"
SOURCE = "My Annuity Store"
SOURCE_LABEL = "My Annuity Store rate marketplace (AnnuityRateWatch data)"
FEEDS = "MYGA new-money spreads by rating"
TERMS = [3, 5, 7, 10]
STATE = os.environ.get("MYGA_STATE", "FL").upper()
PREMIUM = 100_000          # matches the calculator's default account value
MIN_REFRESH_HOURS = 20
MIN_MARKET_ROWS = 100      # the full market is ~650 products; the top slice is 25

# AM Best scale collapsed to the buckets the model actually distinguishes.
# The point of the bucketing is to price the credit-quality tradeoff the
# calculator currently only warns about in prose.
BUCKETS = [
    ("aplus", "A++ / A+", {"A++", "A+"}),
    ("a", "A", {"A"}),
    ("aminus", "A-", {"A-"}),
    ("bplus", "B++ / B+", {"B++", "B+"}),
]
BUCKET_OF = {r: key for key, _label, ratings in BUCKETS for r in ratings}
LABEL_OF = {key: label for key, label, _ in BUCKETS}


# ── Treasury benchmark ────────────────────────────────────────────

def _interp(tenors, yields, target):
    """Linear interpolation across the UST curve, flat past either end.
    Mirrors interpolateCurve() in src/annuityMoneyness.js."""
    pts = []
    for t, v in zip(tenors or [], yields or []):
        m = re.match(r"^([\d.]+)\s*([MY])$", str(t).strip(), re.I)
        if not m or v is None:
            continue
        n = float(m.group(1))
        pts.append((n / 12 if m.group(2).upper() == "M" else n, float(v)))
    if not pts:
        return None
    pts.sort()
    if target <= pts[0][0]:
        return pts[0][1]
    if target >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if target <= x1:
            return y0 + (y1 - y0) * (target - x0) / (x1 - x0)
    return pts[-1][1]


def load_ust():
    try:
        d = json.loads((DATA / "ust.json").read_text())
        return d.get("tenors"), d.get("yields"), d.get("date")
    except Exception as e:
        log.warning(f"  MYGA: no UST curve to spread against ({e})")
        return None, None, None


# ── Parsing ───────────────────────────────────────────────────────

def _to_rate(v):
    """'5.35%' | '5.35' | 5.35 → 5.35. Rejects anything outside a sane band."""
    if isinstance(v, (int, float)):
        r = float(v)
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*%?", str(v))
        if not m:
            return None
        r = float(m.group(1))
    if r > 100:
        return None
    if r <= 0.25:          # a fraction rather than a percentage
        r *= 100
    return r if 0.5 <= r <= 20 else None


def _to_rating(v):
    """'A+ (Superior)' → 'A+'.  'AM Best A-' → 'A-'.  'n/a' → None.

    Deliberately case-sensitive, and no \\b anchors. A trailing word boundary
    can never match after '+' (both are non-word characters), which silently
    drops every modifier and collapses A++/A+/A- into a bare 'A' — the exact
    failure that would flatten the ratings ladder this whole file exists to
    measure. The lookarounds do the job \\b cannot.
    """
    s = str(v).strip()
    if re.fullmatch(r"(?i)\s*n\s*/?\s*a\s*", s):
        return None
    m = re.search(r"(?<![A-Za-z])(A\+\+|A\+|A-|A|B\+\+|B\+|B-|B)(?![A-Za-z])", s)
    return m.group(1) if m else None


def _to_term(v):
    m = re.search(r"(\d+)", str(v))
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 20 else None


_ROW = re.compile(r"<tr\b([^>]*)>", re.I)
_ATTR = re.compile(r'([a-z][\w-]*)\s*=\s*"([^"]*)"', re.I)


def market_rows(html):
    """Attributes of every product row (rows carrying data-term), unescaped."""
    rows = []
    for m in _ROW.finditer(html or ""):
        attrs = {k.lower(): unescape(v) for k, v in _ATTR.findall(m.group(1))}
        if "data-term" in attrs:
            rows.append(attrs)
    return rows


def rate_at_premium(row, premium):
    """Rate a `premium` deposit earns, or None if the product won't take it."""
    try:
        bands = json.loads(row.get("data-bands") or "[]")
    except ValueError:
        bands = []
    if bands:
        for b in bands:
            try:
                if float(b["min"]) <= premium <= float(b["max"]):
                    return _to_rate(b["rate"])
            except (KeyError, TypeError, ValueError):
                continue
        return None
    try:
        if float(row.get("data-overallmin") or 0) > premium:
            return None
    except ValueError:
        pass
    return _to_rate(row.get("data-highrate", ""))


def compound_equivalent(simple_pct, years):
    """Simple-interest rate → compound annual yield with the same maturity value."""
    return ((1 + simple_pct / 100 * years) ** (1 / years) - 1) * 100


def _is_simple(row):
    flag = row.get("data-simple")
    if flag is not None:
        return flag.strip() == "1"
    return "simple interest" in row.get("data-product", "").lower()


def parse_market(rows, state=STATE, premium=PREMIUM, terms=TERMS):
    """Product rows → (one quote per carrier and term, products considered).

    Carrier names are used here only to collapse a carrier's variants into
    its best rate; they do not leave this function.
    """
    best, products = {}, 0
    for i, row in enumerate(rows):
        term = _to_term(row.get("data-term", ""))
        rating = _to_rating(row.get("data-rating", ""))
        if term not in terms or not rating:
            continue
        states = {s.strip().upper() for s in row.get("data-states", "").split(",") if s.strip()}
        if state and state not in states:
            continue
        rate = rate_at_premium(row, premium)
        if rate is None:
            continue
        if _is_simple(row):
            rate = compound_equivalent(rate, term)
        products += 1
        carrier = (row.get("data-carrier") or "").strip().lower() or f"row{i}"
        key = (carrier, term)
        if key not in best or rate > best[key]["rate"]:
            best[key] = {"rate": round(rate, 4), "rating": rating, "term": term}
    return list(best.values()), products


def fetch_market(timeout=45):
    req = urllib.request.Request(MARKET_URL, headers={**HDR, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.loads(r.read().decode("utf-8", errors="replace"))
    if not isinstance(payload, dict) or not payload.get("ok") or not isinstance(payload.get("html"), str):
        raise ValueError("unexpected response shape")
    return payload["html"]


# ── Aggregation ───────────────────────────────────────────────────

def _quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def aggregate(quotes, ust_tenors, ust_yields):
    """Quotes → spread distribution by rating bucket and term.

    This is the step that discards carrier identity. Everything downstream
    sees basis points over Treasuries and a sample count, nothing else.
    """
    buckets, overall, ust_used = {}, {}, {}
    by_key = {}
    for q in quotes:
        bucket = BUCKET_OF.get(q["rating"])
        if not bucket:
            continue
        ust = _interp(ust_tenors, ust_yields, q["term"])
        if ust is None:
            continue
        ust_used[q["term"]] = round(ust, 4)
        spread_bp = (q["rate"] - ust) * 100
        by_key.setdefault((bucket, q["term"]), []).append(spread_bp)
        by_key.setdefault(("__all__", q["term"]), []).append(spread_bp)

    for (bucket, term), spreads in sorted(by_key.items()):
        spreads.sort()
        entry = {
            "median_bp": round(median(spreads), 1),
            "top_quartile_bp": round(_quantile(spreads, 0.75), 1),
            "best_bp": round(spreads[-1], 1),
            "n": len(spreads),
            "ust_pct": ust_used.get(term),
        }
        if bucket == "__all__":
            overall[str(term)] = entry
        else:
            buckets.setdefault(bucket, {"label": LABEL_OF[bucket], "terms": {}})
            buckets[bucket]["terms"][str(term)] = entry
    return buckets, overall


# ── Orchestration ─────────────────────────────────────────────────

def _recent_enough():
    try:
        prev = json.loads(OUT.read_text())
    except Exception:
        return False, None
    try:
        ts = datetime.strptime(prev["_fetched"][:19], "%Y-%m-%dT%H:%M:%S")
        fresh = datetime.utcnow() - ts < timedelta(hours=MIN_REFRESH_HOURS)
        # Only a good file earns the skip; a placeholder retries next run.
        return fresh and prev.get("status") == "ok", prev
    except Exception:
        return False, prev


def write_out(obj):
    obj["_fetched"] = datetime.utcnow().isoformat() + "Z"
    OUT.write_text(json.dumps(obj, indent=2))


def fetch_myga():
    if os.environ.get("MYGA_FETCH", "on").lower() in ("off", "0", "false", "no"):
        log.info("  MYGA: disabled via MYGA_FETCH")
        record_source(SOURCE, feeds=FEEDS, ok=False, fallback="cache", note="disabled via MYGA_FETCH")
        return

    fresh, prev = _recent_enough()
    if fresh:
        log.info(f"  MYGA: cached copy is under {MIN_REFRESH_HOURS}h old, skipping fetch")
        record_source(SOURCE, feeds=FEEDS, ok=True,
                      note=f"cached (<{MIN_REFRESH_HOURS}h); rates move weekly at most")
        return

    tenors, yields, ust_date = load_ust()
    if not tenors:
        record_source(SOURCE, feeds=FEEDS, ok=False, fallback="cache", note="no UST curve to spread against")
        raise RuntimeError("ust.json unavailable; cannot derive spreads")

    rows, quotes, products, problem = [], [], 0, None
    try:
        rows = market_rows(fetch_market())
        if len(rows) < MIN_MARKET_ROWS:
            problem = f"only {len(rows)} product rows, not the full market"
        else:
            quotes, products = parse_market(rows, STATE, PREMIUM, TERMS)
    except urllib.error.HTTPError as e:
        problem = f"HTTP {e.code}"
    except Exception as e:
        problem = f"{type(e).__name__}: {e}"
    log.info(f"  MYGA: {len(rows)} products in the market, {products} sold in {STATE} at "
             f"${PREMIUM:,} for {TERMS}y, {len(quotes)} carrier quotes")

    if not quotes:
        note = "no quotes parsed" + (f" ({problem})" if problem else
                                     f" (no {STATE} products at ${PREMIUM:,} in the market rows)")
        log.warning(f"  MYGA: {note}; leaving previous file untouched")
        record_source(SOURCE, feeds=FEEDS, ok=False,
                      fallback="cache" if prev else "static_default", note=note)
        if prev is None:
            write_out({
                "date": datetime.utcnow().strftime("%Y-%m-%d"),
                "state": STATE, "source": SOURCE_LABEL, "url": PAGE_URL,
                "status": "unavailable", "note": note,
                "buckets": {}, "overall": {},
            })
        return f"stale: {note}"

    buckets, overall = aggregate(quotes, tenors, yields)
    write_out({
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "state": STATE,
        "premium": PREMIUM,
        "source": SOURCE_LABEL,
        "url": PAGE_URL,
        "status": "ok",
        "ust_date": ust_date,
        "terms": TERMS,
        "quote_count": len(quotes),
        "product_count": products,
        "market_count": len(rows),
        "note": (f"Derived statistics only. Each carrier's best MYGA rate per term for a ${PREMIUM:,} "
                 f"deposit in {STATE} (simple-interest rates converted to compound), less the "
                 "matched-maturity Treasury, aggregated by AM Best bucket. No carrier names or "
                 "individual quotes are stored or published."),
        "buckets": buckets,
        "overall": overall,
    })
    log.info(f"  myga_spreads.json written ({len(quotes)} carrier quotes from {products} products, "
             f"{len(buckets)} rating buckets, state {STATE})")
    record_source(SOURCE, feeds=FEEDS, ok=True,
                  note=f"{len(quotes)} carrier quotes from {products} products, state {STATE}")


# ── Self-test (no network) ────────────────────────────────────────

def _fixture_row(term, rating, states, carrier, product, bands, simple=False, overallmin=None):
    """A product row in the marketplace's own markup (attributes HTML-escaped)."""
    bands_json = json.dumps([{"min": lo, "max": hi, "rate": r} for lo, hi, r in bands]).replace('"', "&quot;")
    rates = [r for _, _, r in bands]
    return (f'<tr\n  data-term="{term}"\n  data-rating="{rating}"\n  data-states="{states}" data-wy1="0%" '
            f'data-carrier="{carrier}" data-highrate="{max(rates)}" data-lowrate="{min(rates)}" '
            f'data-banding="{int(len(bands) > 1)}" data-overallmin="{overallmin or bands[0][0]}" '
            f'data-bands="{bands_json}" data-product="{product}" data-simple="{int(simple)}">'
            f'<td class="mrt-td mrt-td-cp"><span class="mrt-td-co">{carrier}</span>'
            f'<span class="mrt-td-pr">{product}</span></td>'
            f'<td class="mrt-td mrt-td-rt"><span class="mrt-rate">{max(rates):.2f}%</span></td></tr>')


FIXTURE_HTML = "".join([
    "<tr><th>Compare</th><th>Company &amp; Product Name</th></tr>",          # header row: ignored
    _fixture_row(5, "A+", "AL,FL,TX", "Redacted Life", "Plain 5", [(10000, 1000000, 5.60)]),
    _fixture_row(5, "A+", "AL,FL,TX", "Redacted Life", "Plain 5 with rider", [(10000, 1000000, 5.40)]),
    _fixture_row(5, "A+", "CA", "Redacted Life", "Plain 5 (CA)", [(10000, 1000000, 5.90)]),
    _fixture_row(5, "A-", "FL,GA", "Banded Mutual", "Tiered 5", [(5000, 99999, 6.00), (100000, 1000000, 6.35)]),
    _fixture_row(5, "A-", "FL", "Simple Co", "Simple 5 (Simple Interest)", [(5000, 1000000, 7.00)], simple=True),
    _fixture_row(5, "A", "FL", "Jumbo Life", "Jumbo 5", [(250000, 2000000, 6.80)]),
    _fixture_row(5, "B-", "FL", "Weak Life", "Weak 5", [(5000, 1000000, 6.45)]),
    _fixture_row(4, "A", "FL", "Odd Term Life", "Four", [(5000, 1000000, 5.50)]),
    _fixture_row(7, "NR", "FL", "Unrated Life", "Seven", [(5000, 1000000, 6.90)]),
    _fixture_row(7, "A", "AK,FL", "Redacted Life", "Plain 7", [(10000, 1000000, 5.80)]),
])


def selftest():
    ok = fails = 0

    def check(name, cond, got=None, want=None):
        nonlocal ok, fails
        if cond:
            ok += 1
            print(f"  ok   {name}")
        else:
            fails += 1
            print(f"  FAIL {name}\n         got  {got}\n         want {want}")

    t = ["1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "30Y"]
    y = [4.14, 4.33, 4.36, 4.43, 4.55, 4.69, 5.16]

    print("\ncurve interpolation (must match the JS engine)")
    check("exact node", _interp(t, y, 5) == 4.43, _interp(t, y, 5), 4.43)
    check("midpoint 6Y", abs(_interp(t, y, 6) - 4.49) < 1e-9, _interp(t, y, 6), 4.49)
    check("flat past the end", _interp(t, y, 40) == 5.16, _interp(t, y, 40), 5.16)
    check("nulls skipped", _interp(["1Y", "2Y"], [None, 4.0], 2) == 4.0, None, 4.0)

    print("\nvalue coercion")
    check("percent string", _to_rate("5.35%") == 5.35, _to_rate("5.35%"), 5.35)
    check("bare number", _to_rate(5.35) == 5.35, _to_rate(5.35), 5.35)
    check("fraction promoted", _to_rate(0.0535) == 5.35, _to_rate(0.0535), 5.35)
    check("absurd rate rejected", _to_rate(250) is None, _to_rate(250), None)
    check("zero rejected", _to_rate(0) is None, _to_rate(0), None)
    check("A+ parsed", _to_rating("A+ (Superior)") == "A+", _to_rating("A+ (Superior)"), "A+")
    check("A- not read as A", _to_rating("A-") == "A-", _to_rating("A-"), "A-")
    check("no rating", _to_rating("n/a") is None, _to_rating("n/a"), None)
    check("N/A uppercase", _to_rating("N/A") is None, _to_rating("N/A"), None)
    check("NR is no rating", _to_rating("NR") is None, _to_rating("NR"), None)
    check("A++ not truncated", _to_rating("A++ (Superior)") == "A++", _to_rating("A++ (Superior)"), "A++")
    check("prefix text ignored", _to_rating("AM Best A-") == "A-", _to_rating("AM Best A-"), "A-")
    check("bare A still works", _to_rating("A") == "A", _to_rating("A"), "A")
    check("B++ parsed", _to_rating("B++") == "B++", _to_rating("B++"), "B++")

    print("\nsimple interest")
    ce = compound_equivalent(7.00, 5)
    check("7.00% simple over 5y ≈ 6.19% compound (the site's own figure)", round(ce, 2) == 6.19, ce, 6.19)
    ce7 = compound_equivalent(7.10, 7)
    check("7.10% simple over 7y ≈ 5.93%", round(ce7, 2) == 5.93, ce7, 5.93)
    check("one year: simple = compound", abs(compound_equivalent(5.0, 1) - 5.0) < 1e-9, None, 5.0)

    print("\nmarket rows")
    rows = market_rows(FIXTURE_HTML)
    check("product rows only (header skipped)", len(rows) == 10, len(rows), 10)
    check("attributes unescaped (bands JSON readable)", json.loads(rows[3]["data-bands"])[1]["rate"] == 6.35,
          rows[3].get("data-bands"), "6.35 in band 2")
    check("newlines inside the tag tolerated", rows[0]["data-rating"] == "A+", rows[0].get("data-rating"), "A+")
    check("banded: $100k earns the upper band", rate_at_premium(rows[3], 100_000) == 6.35,
          rate_at_premium(rows[3], 100_000), 6.35)
    check("banded: $50k earns the lower band", rate_at_premium(rows[3], 50_000) == 6.00,
          rate_at_premium(rows[3], 50_000), 6.00)
    check("deposit below the minimum: not offered", rate_at_premium(rows[5], 100_000) is None,
          rate_at_premium(rows[5], 100_000), None)
    unbanded = {"data-highrate": "5.75", "data-overallmin": "10000"}
    check("no bands: falls back to the headline rate", rate_at_premium(unbanded, 100_000) == 5.75,
          rate_at_premium(unbanded, 100_000), 5.75)
    check("no bands, minimum above deposit: not offered",
          rate_at_premium({**unbanded, "data-overallmin": "250000"}, 100_000) is None, None, None)

    quotes, products = parse_market(rows, "FL", 100_000, [3, 5, 7, 10])
    by = {(q["rating"], q["term"]): q["rate"] for q in quotes}
    check("CA-only variant excluded for FL", 5.90 not in by.values(), by, "no 5.90")
    check("a carrier's variants collapse to its best rate", by.get(("A+", 5)) == 5.60, by.get(("A+", 5)), 5.60)
    am5 = sorted(q["rate"] for q in quotes if (q["rating"], q["term"]) == ("A-", 5))
    check("simple interest converted before comparing", am5 == [6.1859, 6.35], am5,
          "[6.1859 compound, 6.35 banded] (not 7.00 simple)")
    check("off-list term dropped", all(q["term"] != 4 for q in quotes), quotes, "no 4y")
    check("unrated dropped", ("A", 7) in by and len([q for q in quotes if q["term"] == 7]) == 1, quotes, "only A 7y")
    check("one quote per carrier and term", len(quotes) == 5, len(quotes), 5)
    check("products counted after state/size filters", products == 6, products, 6)
    q_any, _ = parse_market(rows, "", 100_000, [5])
    check("no state filter: CA variant still collapses into its carrier",
          {(q["rating"], q["rate"]) for q in q_any} >= {("A+", 5.90)} and len(q_any) == 4, q_any, "4 carriers")

    print("\naggregation — the step that discards carrier identity")
    quotes = [
        {"rate": 5.60, "rating": "A+", "term": 5},
        {"rate": 5.70, "rating": "A+", "term": 5},
        {"rate": 5.90, "rating": "A-", "term": 5},
        {"rate": 6.10, "rating": "A-", "term": 5},
        {"rate": 5.00, "rating": "C", "term": 5},   # unrated bucket, dropped
    ]
    buckets, overall = aggregate(quotes, t, y)
    # UST 5Y = 4.43, so A+ spreads are 117bp and 127bp → median 122bp
    check("A+ median spread", buckets["aplus"]["terms"]["5"]["median_bp"] == 122.0,
          buckets["aplus"]["terms"]["5"]["median_bp"], 122.0)
    check("A- pays more than A+",
          buckets["aminus"]["terms"]["5"]["median_bp"] > buckets["aplus"]["terms"]["5"]["median_bp"],
          None, "A- > A+")
    check("unmapped rating dropped", "C" not in str(buckets), None, "no C bucket")
    check("overall pools every bucket", overall["5"]["n"] == 4, overall["5"]["n"], 4)
    check("UST recorded for provenance", buckets["aplus"]["terms"]["5"]["ust_pct"] == 4.43,
          buckets["aplus"]["terms"]["5"]["ust_pct"], 4.43)
    blob = json.dumps({"buckets": buckets, "overall": overall})
    check("no carrier identity survives aggregation",
          "carrier" not in blob.lower() and "Life" not in blob, None, "clean")
    check("no raw rates survive either", "5.6" not in blob and "6.1" not in blob, None, "spreads only")
    fb, fo = aggregate(parse_market(market_rows(FIXTURE_HTML), "FL", 100_000, TERMS)[0], t, y)
    fblob = json.dumps({"buckets": fb, "overall": fo})
    check("end to end from market rows: no names", not re.search(r"Redacted|Mutual|Simple Co|Life", fblob),
          fblob[:200], "clean")

    print("\nno-curve guard")
    b2, o2 = aggregate(quotes, None, None)
    check("no UST ⇒ no output rather than wrong output", b2 == {} and o2 == {}, (b2, o2), ({}, {}))

    print(f"\n{ok} passed, {fails} failed\n")
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="run offline logic tests")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    fetch_myga()
    flush_source_health()
