#!/usr/bin/env python3
"""Spread-earnings disclosures of PE-backed life reinsurers, from SEC filings.

Writes data/reinsurer_spreads.json: 12 quarters per company of what each one
actually discloses, every value linked to the filing it came from.

  Athene (Apollo)                    spread related earnings ($m) and net
                                     investment spread (%), from the
                                     quarterly financial supplement (8-K)
  Global Atlantic (KKR)              insurance operating earnings ($m),
                                     from KKR's earnings release (8-K)
  Brookfield Wealth Solutions        distributable operating earnings ($m),
  (Brookfield; incl. American Equity) from its quarterly results (6-K)

The metrics are company-defined non-GAAP measures and are not comparable
with each other; each is shown on its own definition. Private reinsurers
(Prismic, Fortitude, Wilton, Talcott, ...) don't file with the SEC and are
listed as not covered.

How it works: EDGAR's submissions API lists each company's filings; earnings
filings newer than the backfill window are opened, their HTML tables read,
and any table with quarter columns (2Q'24 / Q2 2024 / "Three Months Ended
June 30, 2026" / "June 30, 2026") and a matching row label is harvested.
Overlapping quarters take the newest filing's figure, and a changed figure
is kept as a restatement. Processed filings are remembered, so a routine
run makes one request per company. When a filing mentions a metric but no
value can be read, the run logs the row and headers it saw.

Run: python scripts/fetch_reinsurer_spreads.py
"""
import html as htmllib
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetchlib import record_source, flush_source_health  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reinsurer_spreads")

DATA = Path(__file__).parent.parent / "data"
OUT = DATA / "reinsurer_spreads.json"
QUARTERS_SHOWN = 12
QUARTERS_KEPT = 16
BACKFILL_DAYS = 1300           # ~3.5 years: 12 quarters plus filing lag
PARSER_VERSION = 1             # bump to re-read every filing after a parser change
REQUEST_GAP = 0.15             # SEC asks for <= 10 requests/second
MAX_FILINGS_PER_RUN = 40       # per company; the first backfill finishes over a few runs
TIME_BUDGET = 180              # seconds per run; unread filings wait for the next run

# SEC requires a User-Agent identifying the requester. Set the SEC_USER_AGENT
# secret to "Name contact@example.com" to use your own.
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip() or (
    "bermuda-market-intel/1.0 (github.com/Ubermensch-6920/bermuda-market-intel; "
    "Ubermensch-6920@users.noreply.github.com)")

COMPANIES = [
    {
        "key": "athene", "name": "Athene", "owner": "Apollo", "cik": 1527469,
        "forms": ("8-K",), "items": ("2.02", "7.01"), "doc_hint": r"financialsupp",
        "source": "Athene quarterly financial supplement (Form 8-K exhibit)",
        "metrics": {
            "earnings": {"label": "Spread related earnings (SRE)", "unit": "usd_m", "bounds": (100, 5000),
                         "rows": [r"^spread related earnings$"]},
            "spread": {"label": "Net investment spread", "unit": "pct", "bounds": (0.2, 5.0),
                       "rows": [r"^net investment spread$"]},
        },
        "definition": ("SRE: pre-tax operating earnings of the retirement business excluding market "
                       "volatility and non-operating items, net of financing costs. Net investment "
                       "spread: SRE divided by average net invested assets, annualized."),
    },
    {
        "key": "global_atlantic", "name": "Global Atlantic", "owner": "KKR", "cik": 1404912,
        "forms": ("8-K",), "items": ("2.02",), "doc_hint": r"(ex|exhibit)[-_]?99|earnings|release|supplement",
        "source": "KKR quarterly earnings release, Insurance segment (Form 8-K exhibit)",
        "metrics": {
            "earnings": {"label": "Insurance operating earnings", "unit": "usd_m", "bounds": (30, 3000),
                         "rows": [r"^insurance (segment )?operating earnings$", r"^operating earnings - insurance$"]},
        },
        "definition": ("KKR's Insurance segment (Global Atlantic) operating earnings: net investment income "
                       "less net cost of insurance and G&A, after tax and noncontrolling interests. "
                       "KKR does not disclose a spread percentage."),
    },
    {
        "key": "brookfield_ws", "name": "Brookfield Wealth Solutions", "owner": "Brookfield", "cik": 1837429,
        "forms": ("6-K",), "items": None, "doc_hint": r"(ex|exhibit)[-_]?99|press|release|results",
        "source": "Brookfield Wealth Solutions quarterly results (Form 6-K exhibit)",
        "metrics": {
            "earnings": {"label": "Distributable operating earnings (DOE)", "unit": "usd_m", "bounds": (20, 5000),
                         "rows": [r"^distributable operating earnings$", r"^doe$"]},
        },
        "definition": ("Brookfield's distributable operating earnings across its annuity (incl. American "
                       "Equity), P&C and life businesses. Not a spread-only measure; no consistent spread "
                       "percentage is disclosed."),
    },
]

NOT_COVERED = [
    {"name": "Prismic Re", "detail": (
        "Private Bermuda reinsurer launched by Prudential Financial (20%) and Warburg Pincus (15%). "
        "Prudential accounts for its stake under the equity method and discloses related-party "
        "reinsurance balances, but no Prismic earnings or spread.")},
    *({"name": n, "detail": "Privately held; no spread or operating-earnings measure published in SEC filings."}
      for n in ("Fortitude Re", "Wilton Re", "Resolution Re", "Talcott", "Venerable", "Aspida",
                "Kuvare", "Somerset Re", "Martello Re", "Monument Re", "Catalina")),
]


# ── HTTP ──────────────────────────────────────────────────────────────────────

def sec_get(url, timeout=30):
    for attempt in range(3):
        time.sleep(REQUEST_GAP)
        req = urllib.request.Request(url, headers={"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            if e.code == 403:
                raise RuntimeError(f"SEC refused the request (403) — set the SEC_USER_AGENT secret "
                                   f"to 'Name contact@example.com': {url}") from e
            raise


def sec_json(url):
    return json.loads(sec_get(url))


# ── HTML tables ───────────────────────────────────────────────────────────────

class _Tables(HTMLParser):
    """Every <table> as rows of (text, colspan), plus the text just before it."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._stack, self._recent = [], [], []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._stack.append({"rows": [], "context": " ".join(self._recent)[-400:]})
        elif not self._stack:
            return
        elif tag == "tr":
            self._stack[-1]["rows"].append([])
        elif tag in ("td", "th"):
            t = self._stack[-1]
            if not t["rows"]:
                t["rows"].append([])
            span = dict(attrs).get("colspan") or "1"
            t["rows"][-1].append(["", int(span) if span.isdigit() else 1])
        elif tag == "br":
            self.handle_data(" ")

    def handle_endtag(self, tag):
        if tag == "table" and self._stack:
            self.tables.append(self._stack.pop())

    def handle_data(self, data):
        if self._stack:
            t = self._stack[-1]
            if t["rows"] and t["rows"][-1]:
                t["rows"][-1][-1][0] += data
        elif data.strip():
            self._recent.append(data.strip())
            self._recent = self._recent[-40:]


def html_tables(html):
    p = _Tables()
    p.feed(html)
    out = []
    for t in p.tables:
        rows = [[(" ".join(txt.replace("\xa0", " ").split()), span) for txt, span in r] for r in t["rows"]]
        out.append({"rows": [r for r in rows if any(txt for txt, _ in r)], "context": t["context"]})
    return out


def _grid(row):
    """[(text, start_col, end_col)] for a row of (text, colspan) cells."""
    cells, col = [], 0
    for txt, span in row:
        cells.append((txt, col, col + span))
        col += span
    return cells


# ── Periods and values ────────────────────────────────────────────────────────

MONTHS = {m: i + 1 for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
_SKIP = re.compile(r"six months|nine months|twelve months|year(s)? ended|ytd|year[- ]to[- ]date|full year|\bfy\b|"
                   r"change|variance|%\s*chg|vs\.?", re.I)
_YEAR = re.compile(r"^(19|20)\d{2}$")
_MONTH = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)


def _year(s):
    y = int(s)
    return y + 2000 if y < 100 else y


def parse_period(text):
    """'2Q\'24' / 'Q2 2024' / 'Three Months Ended June 30, 2026' / 'June 30, 2026' /
    '6/30/2026' -> '2026Q2'; None for anything that isn't a single quarter."""
    t = text.replace("’", "'").replace("‘", "'").strip()
    if not t or _SKIP.search(t):
        return None
    m = re.search(r"\b([1-4])Q\s*'?\s*(\d{4}|\d{2})\b", t, re.I) or re.search(r"\bQ([1-4])\s*'?\s*(\d{4}|\d{2})\b", t, re.I)
    if m:
        return f"{_year(m.group(2))}Q{m.group(1)}"
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b", t, re.I)
    if m:
        month, day, year = MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b", t)
        if not m:
            return None
        month, day, year = int(m.group(1)), int(m.group(2)), _year(m.group(3))
    if month % 3 or day < 28:
        return None
    return f"{year}Q{month // 3}"


def parse_value(text):
    """'$ 1,234.5' / '(12)' / '1.58%' / '1.58 %' -> float; None for dashes and words."""
    t = text.replace("$", "").replace("%", "").replace(",", "").replace("—", "").replace("–", "").strip()
    neg = t.startswith("(") or t.endswith(")")
    t = t.strip("() ")
    if not re.fullmatch(r"-?\d+(\.\d+)?", t):
        return None
    v = float(t)
    return -v if neg else v


def _norm_label(text):
    t = re.sub(r"\(\d+\)|\[\d+\]|\*+", "", text.lower())
    t = re.sub(r"[\s:$]+$", "", t.replace("—", "-")).strip()
    return re.sub(r"\s+", " ", t)


def _unit_scale(context_text):
    t = context_text.lower()
    if "in thousands" in t or "000s" in t or "$000" in t:
        return 0.001
    if "in billions" in t:
        return 1000.0
    return 1.0


def _header_columns(rows):
    """Period per column span from the header rows (those above the first data
    row). Multi-row headers are combined column by column, so 'Three Months
    Ended June 30,' over '2026 | 2025' reads as two quarters."""
    header_rows = []
    for r in rows:
        label = r[0][0] if r else ""
        nums = [txt for txt, _ in r[1:] if parse_value(txt) is not None and not _YEAR.match(txt.strip())]
        if label and nums:
            break
        header_rows.append(_grid(r))
    if not header_rows:
        return []
    width = max(c[2] for g in header_rows for c in g)
    col_text = [[] for _ in range(width)]
    for g in header_rows:
        for txt, a, b in g:
            # A title row across the whole table ("... and change in ...") would
            # otherwise colour every column; keep wide cells only if they carry
            # a month (e.g. "Three Months Ended June 30,").
            if (b - a) >= 0.8 * width and _SKIP.search(txt) and not _MONTH.search(txt):
                continue
            for c in range(a, b):
                if txt:
                    col_text[c].append(txt)
    spans, c = [], 0
    while c < width:
        period = parse_period(" ".join(col_text[c]))
        start = c
        while c + 1 < width and col_text[c + 1] == col_text[c]:
            c += 1
        if period:
            spans.append((period, start, c + 1))
        c += 1
    return spans


def extract_metrics(html, metric_specs):
    """{metric: {quarter: value}} from every table with quarter columns.
    Also returns the rows that matched a label but yielded no values."""
    found, misses = {}, []
    for table in html_tables(html):
        rows = table["rows"]
        spans = None
        for r in rows:
            if not r:
                continue
            label = _norm_label(r[0][0])
            for key, spec in metric_specs.items():
                if not any(re.search(p, label) for p in spec["rows"]):
                    continue
                if spans is None:
                    spans = _header_columns(rows)
                values = {}
                cells = _grid(r)
                for period, a, b in spans:
                    vals = [parse_value(t) for t, s, e in cells if s < b and e > a and s > 0]
                    vals = [v for v in vals if v is not None]
                    if len(vals) == 1:
                        values[period] = vals[0]
                if not values:
                    # Fallback: same count of numbers and quarter columns, read in order.
                    nums = [v for v in (parse_value(t) for t, _ in r[1:]) if v is not None]
                    if spans and len(nums) == len(spans):
                        values = {p: v for (p, _, _), v in zip(spans, nums)}
                if not values:
                    misses.append({"metric": key, "row": [t for t, _ in r][:14],
                                   "headers": [p for p, _, _ in (spans or [])]})
                    continue
                scale = _unit_scale(table["context"] + " " + " ".join(t for row in rows[:3] for t, _ in row)) \
                    if spec["unit"] == "usd_m" else 1.0
                lo, hi = spec["bounds"]
                for q, v in values.items():
                    v = round(v * scale, 2)
                    if lo <= v <= hi:
                        found.setdefault(key, {}).setdefault(q, v)
                    else:
                        log.warning(f"    {key} {q}: {v} outside plausible range {lo}-{hi}; ignored")
    return found, misses


# ── EDGAR filings ─────────────────────────────────────────────────────────────

def list_filings(company, since):
    """Earnings filings for a company since `since`, oldest first."""
    cik = company["cik"]
    sub = sec_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    pages = [sub["filings"]["recent"]]
    for extra in sub["filings"].get("files", []):
        if extra.get("filingTo", "9999") >= since.isoformat():
            pages.append(sec_json(f"https://data.sec.gov/submissions/{extra['name']}"))
    out = []
    for page in pages:
        for i, form in enumerate(page.get("form", [])):
            filed = page["filingDate"][i]
            if form not in company["forms"] or filed < since.isoformat():
                continue
            items = (page.get("items") or [""] * len(page["form"]))[i] or ""
            if company["items"] and not any(it in items for it in company["items"]):
                continue
            out.append({"form": form, "filed": filed, "accession": page["accessionNumber"][i],
                        "primary": page["primaryDocument"][i]})
    return sorted({f["accession"]: f for f in out}.values(), key=lambda f: f["filed"])


def filing_documents(company, filing):
    """Candidate HTML documents in a filing: name hints first, primary last."""
    cik, acc = company["cik"], filing["accession"].replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}"
    idx = sec_json(f"{base}/index.json")
    names = [i["name"] for i in idx.get("directory", {}).get("item", [])
             if i.get("name", "").lower().endswith((".htm", ".html")) and "index" not in i["name"].lower()]
    hinted = [n for n in names if re.search(company["doc_hint"], n, re.I) and n != filing["primary"]]
    others = [n for n in names if n not in hinted and n != filing["primary"]]
    ordered = hinted + others[:3] + ([filing["primary"]] if filing["primary"] in names else [])
    return [(n, f"{base}/{n}") for n in ordered[:5]]


def plain_text(html):
    """Tag-free, entity-decoded, single-spaced text for cheap 'does this
    document mention the metric at all' checks."""
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", html)).replace("\xa0", " ").split())


def mentions_metric(html, company):
    text = plain_text(html).lower()
    return any(re.search(p.strip("^$"), text) for s in company["metrics"].values() for p in s["rows"])


def merge_points(store, metric, quarter, value, filing, url):
    """Newest filing wins for a quarter; a changed figure records what it replaced."""
    pts = store.setdefault(metric, {})
    prev = pts.get(quarter)
    if prev and prev["filed"] > filing["filed"]:
        return
    point = {"value": value, "filed": filing["filed"], "form": filing["form"], "url": url}
    if prev and abs(prev["value"] - value) > 1e-9:
        point["revised_from"] = prev["value"]
    elif prev and prev.get("revised_from") is not None:
        point["revised_from"] = prev["revised_from"]
    pts[quarter] = point


def update_company(company, state, since, deadline=None):
    """Read new earnings filings into state["points"]; returns a status note.
    Stops at `deadline` (time.monotonic()) without marking the rest read."""
    processed = state.setdefault("processed", {})
    points = state.setdefault("points", {})
    filings = list_filings(company, since)
    pending = [f for f in filings if processed.get(f["accession"]) != PARSER_VERSION]
    # Newest first, so the latest quarters land first; merge_points compares
    # filing dates, so order doesn't affect which figure wins.
    new = sorted(pending, key=lambda f: f["filed"], reverse=True)[:MAX_FILINGS_PER_RUN]
    log.info(f"  {company['name']}: {len(filings)} earnings filings since {since}, "
             f"{len(pending)} unread, reading {len(new)}")
    misses_logged, done = 0, 0
    for f in new:
        if deadline is not None and time.monotonic() > deadline:
            log.info(f"  {company['name']}: time budget used; {len(new) - done} filing(s) left for the next run")
            break
        got_any = False
        for name, url in filing_documents(company, f):
            html = sec_get(url, timeout=60)
            if not mentions_metric(html, company):
                continue
            found, misses = extract_metrics(html, company["metrics"])
            for metric, by_q in found.items():
                for q, v in by_q.items():
                    merge_points(points, metric, q, v, f, url)
            if found:
                got_any = True
                log.info(f"    {f['filed']} {name}: " + ", ".join(f"{m} {sorted(v)[0]}..{sorted(v)[-1]}" for m, v in found.items()))
                break
            for m in misses[:2]:
                if misses_logged < 6:
                    log.warning(f"    {f['filed']} {name}: '{m['metric']}' row found but no values read; "
                                f"row={m['row']} quarter-columns={m['headers']}")
                    misses_logged += 1
        processed[f["accession"]] = PARSER_VERSION
        done += 1
        if not got_any:
            log.info(f"    {f['filed']} {f['accession']}: no target metrics")
    return f"{done} filing(s) read, {len(pending) - done} left for later runs"


def trim(points, keep=QUARTERS_KEPT):
    for metric, by_q in points.items():
        for q in sorted(by_q)[:-keep]:
            del by_q[q]


def build_output(states, errors):
    companies = []
    for c in COMPANIES:
        st = states.get(c["key"], {})
        pts = st.get("points", {})
        metrics = {}
        for key, spec in c["metrics"].items():
            series = [{"quarter": q, **p} for q, p in sorted(pts.get(key, {}).items())][-QUARTERS_SHOWN:]
            metrics[key] = {"label": spec["label"], "unit": spec["unit"], "points": series}
        has = any(m["points"] for m in metrics.values())
        companies.append({
            "key": c["key"], "name": c["name"], "owner": c["owner"], "cik": c["cik"],
            "source": c["source"], "definition": c["definition"], "metrics": metrics,
            "status": "ok" if has else ("error" if c["key"] in errors else "no_data"),
            "note": errors.get(c["key"]),
            "edgar_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={c['cik']}",
            "_state": {"processed": st.get("processed", {}), "points": pts},
        })
    return {
        "updated": datetime.utcnow().isoformat() + "Z",
        "quarters": QUARTERS_SHOWN,
        "parser_version": PARSER_VERSION,
        "companies": companies,
        "not_covered": NOT_COVERED,
        "note": ("Company-defined non-GAAP measures; not comparable across companies. "
                 "Each value links to the SEC filing it was read from; where a later filing "
                 "restated a quarter, the newest figure is shown."),
    }


def load_states():
    try:
        prev = json.loads(OUT.read_text())
    except Exception:
        return {}
    return {c["key"]: c.get("_state", {}) for c in prev.get("companies", [])}


def main():
    log.info("REINSURER SPREADS: reading SEC filings")
    since = date.today() - timedelta(days=BACKFILL_DAYS)
    states, errors = load_states(), {}
    deadline = time.monotonic() + TIME_BUDGET
    for c in COMPANIES:
        st = states.setdefault(c["key"], {})
        try:
            update_company(c, st, since, deadline)
            trim(st.get("points", {}))
        except Exception as e:
            errors[c["key"]] = f"{type(e).__name__}: {e}"
            log.warning(f"  {c['name']}: {errors[c['key']]}")
    out = build_output(states, errors)
    OUT.write_text(json.dumps(out, indent=2))
    ok = [c["name"] for c in out["companies"] if c["status"] == "ok"]
    log.info(f"  wrote {OUT.name}: data for {', '.join(ok) or 'none'}")
    record_source("SEC EDGAR", "PE reinsurer spread disclosures", ok=len(errors) < len(COMPANIES),
                  fallback=None if not errors else "cache",
                  note="; ".join(f"{k}: {v[:80]}" for k, v in errors.items()) or None)
    try:
        flush_source_health()
    except Exception as e:
        log.warning(f"source health flush: {e}")


if __name__ == "__main__":
    main()
