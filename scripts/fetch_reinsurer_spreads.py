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

Fallback: quarters the SEC filings didn't supply (EDGAR unreachable, or a
table the parser can't read) are filled from the company's own earnings
materials: Apollo's earnings-call transcript (ir.apollo.com) for Athene and
the results release on Brookfield's site for BWS. Those figures are read
from prose (scripts/earnings_materials.py), marked with their source, and
replaced as soon as the SEC filing for that quarter is read. KKR posts no
transcripts of its own, so Global Atlantic has no fallback.

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
from fetchlib import HDR, record_source, flush_source_health  # noqa: E402
import earnings_materials as em  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reinsurer_spreads")

DATA = Path(__file__).parent.parent / "data"
OUT = DATA / "reinsurer_spreads.json"
QUARTERS_SHOWN = 12
QUARTERS_KEPT = 16
BACKFILL_DAYS = 1300           # ~3.5 years: 12 quarters plus filing lag
PARSER_VERSION = 2             # bump to re-read every filing after a parser change
REQUEST_GAP = 0.15             # SEC asks for <= 10 requests/second
MAX_FILINGS_PER_RUN = 40       # per company; the first backfill finishes over a few runs
TIME_BUDGET = 180              # seconds per run; unread filings wait for the next run
RESULTS_LAG_DAYS = 50          # a quarter's results are expected this long after quarter end
MAX_FALLBACK_DOCS = 6          # transcripts/releases opened per company per run
FALLBACK_RETRY_DAYS = 14       # a missing fallback document is retried after this long

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
                         "rows": [r"^spread related earnings( \(sre\))?$"],
                         "prose": [r"spread[- ]related earnings", r"\bSRE\b"]},
            "net_spread": {"label": "Net spread (SRE ÷ avg net invested assets)", "unit": "pct", "bounds": (0.2, 4.0),
                           "rows": [r"^net spread$"], "prose": [r"\bnet spread\b"]},
            "spread": {"label": "Net investment spread", "unit": "pct", "bounds": (0.2, 5.0),
                       "rows": [r"^net investment spread$"],
                       "prose": [r"net investment spread"]},
        },
        # Apollo posts each call's transcript PDF on its IR site, linked from
        # the home page (latest quarter) and from each earnings event page.
        "fallback": {
            "kind": "call", "label": "Apollo earnings call transcript (ir.apollo.com)",
            "index": ["https://ir.apollo.com/", "https://ir.apollo.com/news-events/events"],
            "follow": r"/news-events/events/detail/\d{8}-[^\"']*(earnings|quarter|[1-4]q)",
            "doc": r"transcript[^\"']*\.pdf",
        },
        "definition": ("SRE: pre-tax operating earnings of the retirement business excluding market "
                       "volatility and non-operating items, net of financing costs. Net spread: SRE as a "
                       "percentage of average net invested assets, annualized; this is the figure Apollo "
                       "quotes on its calls. Net investment spread: net investment earned rate plus "
                       "strategic capital management fees, less total cost of funds (higher, as it is "
                       "before operating and financing costs)."),
        "scope": "Apollo-owned; Bermuda: Athene Life Re and the ACRA / ADIP sidecars.",
    },
    {
        "key": "global_atlantic", "name": "Global Atlantic", "owner": "KKR", "cik": 1404912,
        "forms": ("8-K",), "items": ("2.02",), "doc_hint": r"(ex|exhibit)[-_]?99|earnings|release|supplement",
        "text_rows": True,  # the release is slide images with the slide text hidden behind them
        "source": "KKR quarterly earnings release, Insurance segment (Form 8-K exhibit)",
        "metrics": {
            "earnings": {"label": "Insurance operating earnings", "unit": "usd_m", "bounds": (30, 3000),
                         "rows": [r"^insurance (segment )?operating earnings$", r"^operating earnings - insurance$"]},
        },
        "fallback": None,
        "fallback_note": ("KKR doesn't post call transcripts on its own site, and third-party transcript "
                          "sites are paywalled or bar automated reading, so these figures come from SEC filings only."),
        "definition": ("KKR's Insurance segment (Global Atlantic) operating earnings: net investment income "
                       "less net cost of insurance and general and administrative costs. Basis changes: KKR "
                       "owned about 63% of Global Atlantic until 2 Jan 2024 and 100% after; from 2025 the "
                       "measure is cash-based and excludes marks on investments. KKR does not disclose a "
                       "spread percentage."),
        "scope": "KKR-owned; Bermuda reinsurance entities and the Ivy sidecars.",
    },
    {
        "key": "brookfield_ws", "name": "Brookfield Wealth Solutions", "owner": "Brookfield", "cik": 1837429,
        "forms": ("6-K",), "items": None, "doc_hint": r"exh_?99|(ex|exhibit)[-_]?99|press|release|results|bnt-\d{8}_d",
        "source": "Brookfield Wealth Solutions quarterly results (Form 6-K exhibit)",
        "metrics": {
            "earnings": {"label": "Distributable operating earnings (DOE)", "unit": "usd_m", "bounds": (20, 5000),
                         "rows": [r"^distributable operating earnings$", r"^doe$"],
                         "prose": [r"distributable operating earnings", r"\bDOE\b"]},
        },
        # BWS holds no call of its own; its results release sits at a fixed path per quarter.
        "fallback": {
            "kind": "release", "label": "BWS results release (bnt.brookfield.com)",
            "template": ("https://bnt.brookfield.com/sites/brookfield-bnt-v2/files/Brookfield-BN-IR-V2/"
                         "{year}/q{q}/{year}-q{q}-bws-press-release.pdf"),
        },
        "definition": ("Brookfield's distributable operating earnings across its annuity (incl. American "
                       "Equity), P&C and life businesses. Not a spread-only measure; no consistent spread "
                       "percentage is disclosed."),
        "scope": "Brookfield; Bermuda reinsurance platform with American Equity, American National and Just Group.",
    },
]

COMPANIES += [
    {
        "key": "corebridge", "name": "Corebridge Financial", "owner": "Nippon Life stake; Blackstone & BlackRock mandates",
        "cik": 1889539, "forms": ("8-K",), "items": ("2.02",),
        "doc_hint": r"pressr|press|release|earnings|ex(hibit)?[-_]?99",
        "source": "Corebridge quarterly earnings release, consolidated results (Form 8-K exhibit)",
        "metrics": {
            "earnings": {"label": "Adjusted pre-tax operating income (APTOI)", "unit": "usd_m", "bounds": (200, 4000),
                         "rows": [r"^adjusted pre-tax operating income$"], "context": r"consolidated"},
            "base_spread": {"label": "Base spread income", "unit": "usd_m", "bounds": (200, 4000),
                            "rows": [r"^base spread income$"], "context": r"consolidated"},
        },
        "fallback": None,
        "definition": ("APTOI: company-wide operating income before tax (Individual and Group Retirement, Life, "
                       "Institutional), excluding investment gains and losses, market-risk-benefit changes and "
                       "the Fortitude Re funds-withheld results. Base spread income: base portfolio income less "
                       "interest credited, excluding variable investment income; the spread line of the business."),
        "scope": "Fortitude Re legacy reinsurance and its own Bermuda flow reinsurance (from 2024); "
                 "merging with Equitable (all-stock, close expected by end-2026).",
    },
    {
        "key": "fg", "name": "F&G Annuities & Life", "owner": "FNF (about 70%); Blackstone manages assets",
        "cik": 1934850, "forms": ("8-K",), "items": ("2.02",),
        "doc_hint": r"earningsrelease|financialsupp|ex(hibit)?[-_]?99",
        "sec_prose": True,  # the release tables are images; the figure is read from its sentences
        "source": "F&G quarterly earnings release (Form 8-K exhibit)",
        "metrics": {
            "earnings": {"label": "Adjusted net earnings (ANE)", "unit": "usd_m", "bounds": (20, 1500),
                         "rows": [r"^adjusted net earnings( attributable to common shareholders)?$"],
                         "prose": [r"adjusted net earnings"]},
        },
        "fallback": None,
        "definition": ("Adjusted net earnings attributable to common shareholders: net earnings excluding "
                       "mark-to-market effects and other significant items. After tax; not a spread measure."),
        "scope": "Blackstone asset-management partner; F&G Life Re (Bermuda) sold to Ancient effective "
                 "1 Mar 2026; Fort Green Re (Cayman) sidecar since Aug 2025.",
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


def web_get(url, timeout=30):
    """Bytes from a company website, or None when the page doesn't exist (404/410)."""
    time.sleep(REQUEST_GAP)
    req = urllib.request.Request(url, headers=HDR)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return None
        raise


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
_SKIP = re.compile(r"six months|nine months|twelve months|year(s)? ended|ytd|\bltm\b|year[- ]to[- ]date|full year|\bfy\b|"
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
    t = re.sub(r"(?<=[a-z)])\d{1,2}\s*$", "", t)  # footnote marker glued on: "earnings1"
    t = re.sub(r"[\s:$]+$", "", t.replace("—", "-")).strip()
    return re.sub(r"\s+", " ", t)


def _unit_scale(context_text):
    t = context_text.lower()
    if "in thousands" in t or "000s" in t or "$000" in t:
        return 0.001
    if "in billions" in t:
        return 1000.0
    return 1.0


def _row_label(row):
    """A row's label: its first text cell, skipping empty spacer cells and lone
    '$'/'%' marks; '' when the row starts with a number (a header or data row)."""
    for txt, _ in row:
        t = txt.strip()
        if not t or t in ("$", "%"):
            continue
        return "" if parse_value(t) is not None else t
    return ""


_PERIOD_GROUP = re.compile(r"(three|six|nine|twelve) months|quarter|year(s)? ended|\bytd\b", re.I)
_MONTH_DAY = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b", re.I)


def _sequential_periods(rows, context=""):
    """Periods in reading order for headers whose cells don't line up with the
    value columns (Brookfield): the month comes from the label cell or table
    title ('periods ended June 30'), each group ('Three Months Ended', 'Six
    Months Ended') takes its share of the years row in order. None marks a
    non-quarter column (six months, year to date)."""
    header = []
    for r in rows:
        if _row_label(r) and [t for t, _ in r if parse_value(t) is not None and not _YEAR.match(t.strip())]:
            break
        header.append(r)
    texts = [t.strip() for r in header for t, _ in r if t.strip()]
    m = _MONTH_DAY.search(" ".join(texts)) or _MONTH_DAY.search(context[-300:])
    if not m or MONTHS[m.group(1).lower()] % 3:
        return []
    q = MONTHS[m.group(1).lower()] // 3
    years = max(([t.strip() for t, _ in r if _YEAR.match(t.strip())] for r in header), key=len, default=[])
    if not years:
        return []
    groups = [t for t in texts if _PERIOD_GROUP.search(t) and not _YEAR.match(t)]
    if not groups:
        return [] if _SKIP.search(" ".join(texts)) else [f"{y}Q{q}" for y in years]
    if len(years) % len(groups):
        return []
    per, out = len(years) // len(groups), []
    for i, g in enumerate(groups):
        quarterly = re.search(r"three months|quarter", g, re.I) and not re.search(r"six|nine|twelve|year|ytd", g, re.I)
        out += [f"{y}Q{q}" if quarterly else None for y in years[i * per:(i + 1) * per]]
    return out


def _header_columns(rows):
    """Period per column span from the header rows (those above the first data
    row). Multi-row headers are combined column by column, so 'Three Months
    Ended June 30,' over '2026 | 2025' reads as two quarters."""
    header_rows = []
    for r in rows:
        label = _row_label(r)
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
            label = _norm_label(_row_label(r))
            for key, spec in metric_specs.items():
                if not label or not any(re.search(p, label) for p in spec["rows"]):
                    continue
                if spec.get("context") and not re.search(spec["context"], table["context"], re.I):
                    continue  # e.g. Corebridge: the consolidated table, not a segment one
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
                    # Fallback: header groups and years read in order (cells misaligned).
                    periods = _sequential_periods(rows, table["context"])
                    nums = [v for v in (parse_value(t) for t, _ in r) if v is not None]
                    if periods and len(nums) == len(periods):
                        values = {p: v for p, v in zip(periods, nums) if p}
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


_PERIOD_TOKEN = r"(?:[1-4]q\s?'?\d{2}|q[1-4]\s?'?\d{2})(?:\s+(?:ytd|ltm))?"


def extract_text_rows(html, metric_specs):
    """{metric: {quarter: value}} for releases laid out as slide images with the
    slide text hidden behind them (KKR): no HTML tables, but the text reads
    'insurance operating earnings $ 277,932 $ 288,220 $ 536,704 $ 548,550'
    after a header run of period tokens ("2q'25 2q'26 2q'25 ytd 2q'26 ytd").
    Numbers pair with the nearest preceding run of exactly as many tokens;
    year-to-date and LTM columns are dropped."""
    text = plain_text(html).lower().replace("\u2019", "'")
    found = {}
    for key, spec in metric_specs.items():
        lo, hi = spec["bounds"]
        for pat in spec["rows"]:
            row = re.compile("(?:" + pat.strip("^$") + r")\s*(?:\(\d\)|\d)?\s*(?P<nums>(?:\$?\s*\(?-?\d[\d,]*(?:\.\d+)?\)?%?\s*){2,8})")
            for m in row.finditer(text):
                nums = [parse_value(n) for n in re.findall(r"\(?-?\d[\d,]*(?:\.\d+)?\)?", m.group("nums"))]
                before = text[max(0, m.start() - 3000):m.start()]
                runs = [r for r in re.finditer(rf"(?:{_PERIOD_TOKEN}\s+)*{_PERIOD_TOKEN}", before)
                        if len(re.findall(_PERIOD_TOKEN, r.group(0))) == len(nums)]
                if not runs:
                    continue
                run = runs[-1]
                tokens = re.findall(_PERIOD_TOKEN, run.group(0))
                scale = _unit_scale(before[max(0, run.start() - 300):run.end()]) if spec["unit"] == "usd_m" else 1.0
                for tok, v in zip(tokens, nums):
                    q = parse_period(tok)  # None for YTD / LTM columns
                    if q is None or v is None:
                        continue
                    v = round(v * scale, 2)
                    if lo <= v <= hi:
                        found.setdefault(key, {}).setdefault(q, v)
    return found


def extract_from_document(html, company):
    """Tables first; then the hidden-text slide rows (text_rows companies); then
    the release's own sentences (sec_prose companies, one quarter per filing)."""
    found, misses = extract_metrics(html, company["metrics"])
    if not found and company.get("text_rows"):
        found = extract_text_rows(html, company["metrics"])
    if not found and company.get("sec_prose"):
        text = em.html_text(html)
        quarter = em.quarter_from_text(em.normalise(text))
        prose = {k: s for k, s in company["metrics"].items() if s.get("prose")}
        if quarter and prose:
            values, _notes = em.extract_prose_metrics(text, quarter, prose)
            found = {k: {quarter: v} for k, v in values.items()}
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
    """Newest filing wins for a quarter; a changed figure records what it replaced.
    An SEC figure always replaces a fallback (call/release) figure, silently:
    that is not a restatement, just the better source arriving."""
    pts = store.setdefault(metric, {})
    prev = pts.get(quarter)
    if prev and prev.get("source", "sec") != "sec":
        prev = None
    if prev and prev["filed"] > filing["filed"]:
        return
    point = {"value": value, "filed": filing["filed"], "form": filing["form"], "url": url, "source": "sec"}
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
            found, misses = extract_from_document(html, company)
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


# ── Fallback: earnings-call transcripts and results releases ──────────────────

def expected_quarters(today=None, n=QUARTERS_SHOWN):
    """The last n quarters whose results should be public by `today`."""
    today = today or date.today()
    y, q, out = today.year, (today.month - 1) // 3 + 1, []
    while len(out) < n:
        q -= 1
        if q == 0:
            y, q = y - 1, 4
        quarter_end = date(y + (q == 4), (3 * q) % 12 + 1, 1) - timedelta(days=1)
        if quarter_end + timedelta(days=RESULTS_LAG_DAYS) <= today:
            out.append(f"{y}Q{q}")
    return out


def _prose_metrics(company):
    return {k: s for k, s in company["metrics"].items() if s.get("prose")}


def wanted_quarters(company, points, today=None):
    """Expected quarters (newest first) missing at least one prose-readable metric."""
    keys = list(_prose_metrics(company))
    return [q for q in expected_quarters(today) if any(q not in points.get(k, {}) for k in keys)]


def _fresh(seen, url, today):
    mark = seen.get(url)
    if mark is None:
        return True
    if isinstance(mark, str) and mark.startswith("missing:"):
        return (today - date.fromisoformat(mark[8:])).days >= FALLBACK_RETRY_DAYS
    return mark != PARSER_VERSION


def fallback_documents(company, state, wanted, today=None):
    """[(url, quarter or None)] documents worth opening for the wanted quarters, newest first."""
    fb, today = company["fallback"], today or date.today()
    seen = state.setdefault("fallback_seen", {})
    if "template" in fb:
        urls = [(fb["template"].format(year=q[:4], q=q[-1]), q) for q in wanted]
        return [(u, q) for u, q in urls if _fresh(seen, u, today)]
    links, opened = [], set()
    for page in fb["index"]:
        body = web_get(page)
        if body is None:
            continue
        html = body.decode("utf-8", errors="replace")
        links += em.discover_links(html, page, fb["doc"])
        for event in em.discover_links(html, page, fb["follow"]) if fb.get("follow") else []:
            q = em.quarter_from_name(event.rsplit("/", 1)[-1])
            if (q and q not in wanted) or event in opened or len(opened) >= MAX_FALLBACK_DOCS:
                continue
            opened.add(event)
            ev = web_get(event)
            if ev is not None:
                links += em.discover_links(ev.decode("utf-8", errors="replace"), event, fb["doc"])
    out, seen_urls = [], set()
    for url in links:
        q = em.quarter_from_name(url.rsplit("/", 1)[-1])
        if url in seen_urls or (q and q not in wanted) or not _fresh(seen, url, today):
            continue
        seen_urls.add(url)
        out.append((url, q))
    rank = {q: i for i, q in enumerate(wanted)}
    return sorted(out, key=lambda d: rank.get(d[1], len(rank)))


def read_fallback_document(company, url, quarter_hint):
    """(quarter, found, notes) from one transcript/release, or None if it doesn't exist."""
    data = web_get(url, timeout=60)
    if data is None:
        return None
    text = em.pdf_text(data) if data[:5] == b"%PDF-" else em.html_text(data.decode("utf-8", errors="replace"))
    from_text = em.quarter_from_text(em.normalise(text))
    quarter = quarter_hint or from_text
    if not quarter:
        return quarter, {}, {"*": "no quarter named in the document"}
    if quarter_hint and from_text and from_text != quarter_hint:
        return quarter, {}, {"*": f"file name says {quarter_hint}, text says {from_text}"}
    found, notes = em.extract_prose_metrics(text, quarter, _prose_metrics(company))
    return quarter, found, notes


def merge_fallback(store, metric, quarter, value, kind, label, url, read_on):
    """A fallback figure only fills a gap: it never replaces an SEC figure."""
    pts = store.setdefault(metric, {})
    prev = pts.get(quarter)
    if prev and (prev.get("source", "sec") == "sec" or prev["filed"] > read_on):
        return False
    pts[quarter] = {"value": value, "filed": read_on, "form": label, "url": url, "source": kind}
    return True


def update_fallback(company, state, deadline=None, today=None):
    """Fill quarters the SEC filings didn't supply from the company's own earnings materials."""
    fb = company.get("fallback")
    if not fb:
        return
    today = today or date.today()
    points = state.setdefault("points", {})
    wanted = wanted_quarters(company, points, today)
    if not wanted:
        return
    seen = state.setdefault("fallback_seen", {})
    docs = fallback_documents(company, state, wanted, today)
    log.info(f"  {company['name']}: {len(wanted)} quarter(s) without SEC figures; "
             f"{len(docs)} {fb['kind']} document(s) to try")
    for url, hint in docs[:MAX_FALLBACK_DOCS]:
        if deadline is not None and time.monotonic() > deadline:
            log.info(f"  {company['name']}: time budget used; fallback documents left for the next run")
            break
        res = read_fallback_document(company, url, hint)
        if res is None:
            seen[url] = f"missing:{today.isoformat()}"
            continue
        seen[url] = PARSER_VERSION
        quarter, found, notes = res
        for metric, value in found.items():
            merge_fallback(points, metric, quarter, value, fb["kind"], fb["label"], url, today.isoformat())
        log.info(f"    {quarter} {url.rsplit('/', 1)[-1]}: "
                 + (", ".join(f"{k} {v}" for k, v in found.items()) or "nothing read")
                 + (f" ({'; '.join(f'{k}: {v}' for k, v in notes.items())})" if notes else ""))


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
            "source": c["source"], "definition": c["definition"], "scope": c.get("scope"), "metrics": metrics,
            "status": "ok" if has else ("error" if c["key"] in errors else "no_data"),
            "note": errors.get(c["key"]),
            "edgar_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={c['cik']}",
            "fallback_source": (c.get("fallback") or {}).get("label"),
            "fallback_note": c.get("fallback_note"),
            "_state": {"processed": st.get("processed", {}), "points": pts,
                       "fallback_seen": st.get("fallback_seen", {})},
        })
    return {
        "updated": datetime.utcnow().isoformat() + "Z",
        "quarters": QUARTERS_SHOWN,
        "parser_version": PARSER_VERSION,
        "companies": companies,
        "not_covered": NOT_COVERED,
        "note": ("Company-defined non-GAAP measures; not comparable across companies. "
                 "Each value links to the document it was read from: the SEC filing, or, where "
                 "that couldn't be read, the company's earnings call transcript or results release "
                 "(marked as such, and replaced once the filing is read). Where a later filing "
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
        except Exception as e:
            errors[c["key"]] = f"{type(e).__name__}: {e}"
            log.warning(f"  {c['name']}: {errors[c['key']]}")
        try:
            update_fallback(c, st, deadline)
        except Exception as e:
            log.warning(f"  {c['name']} fallback: {type(e).__name__}: {e}")
        trim(st.get("points", {}))
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
