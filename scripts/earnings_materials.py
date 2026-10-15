"""Figures read from earnings-call transcripts and results releases.

The fallback for scripts/fetch_reinsurer_spreads.py when a quarter's SEC
filing can't be read: the same headline numbers are spoken on the call and
printed in the release, just in prose ("Athene reported spread related
earnings of $877 million") instead of a table.

Prose is easy to misread, so extraction is deliberately narrow:
  - only sentences about the document's own quarter (a sentence naming a
    different quarter or year is skipped);
  - no full-year, year-to-date, six-month, guidance or target sentences;
  - no figure that follows a comparison ("up from", "a year ago", "versus");
  - for a movement ("declined 11 basis points to 1.47%") the figure after
    "to" is taken, never the change itself;
  - every candidate must pass the metric's sanity bounds, and when the
    sentences disagree the document is skipped rather than guessed.
"""
import html as htmllib
import io
import re
from collections import Counter
from urllib.parse import urljoin

_QWORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}


# ── Text ──────────────────────────────────────────────────────────────────────

def pdf_text(data):
    """Plain text of a PDF (bytes). Needs pypdf (requirements.txt)."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def html_text(html):
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    return htmllib.unescape(re.sub(r"<[^>]+>", " ", html))


def normalise(text):
    """One line of text: hyphenated line breaks joined, quotes/dashes/spaces unified."""
    text = text.replace("­", "").replace("\xa0", " ")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    text = text.translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"',
                                         "–": "-", "—": "-"}))
    return " ".join(text.split())


def sentences(text):
    # Split after . ! ? when the next word starts a sentence; decimals like
    # "$1.2 billion" and "1.47%" have no space after the point, so they survive.
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[\"(]?[A-Z])", text) if s.strip()]


# ── Which quarter a document is about ─────────────────────────────────────────

def _yr(s):
    y = int(s)
    return y + 2000 if y < 100 else y


def quarter_from_name(name):
    """From a file name or URL: 'APO+2Q26+Transcript.pdf', 'Q2-2026', '2026/q2/…'."""
    s = name.replace("%27", "'")
    for pat, order in ((r"(?<![0-9A-Za-z])([1-4])Q[\s'_+\-]?(\d{4}|\d{2})(?![0-9])", "qy"),
                       (r"(?<![0-9A-Za-z])Q([1-4])[\s'_+\-]?(\d{4}|\d{2})(?![0-9])", "qy"),
                       (r"(?<![0-9])(20\d{2})[/_\-]q([1-4])(?![0-9])", "yq")):
        m = re.search(pat, s, re.I)
        if m:
            q, y = (m.group(1), m.group(2)) if order == "qy" else (m.group(2), m.group(1))
            return f"{_yr(y)}Q{int(q)}"
    return None


def quarter_from_text(text, head=4000):
    """The quarter a transcript or release is about, from its opening text."""
    s = text[:head]
    best = None
    for pat, conv in ((r"\b(first|second|third|fourth)[- ]quarter(?: of)?,? (20\d{2})\b", lambda m: (_QWORD[m.group(1).lower()], m.group(2))),
                      (r"\b([1-4])Q[ ']?(20\d{2}|\d{2})\b", lambda m: (int(m.group(1)), m.group(2))),
                      (r"\bQ([1-4])[ ']?(20\d{2}|\d{2})\b", lambda m: (int(m.group(1)), m.group(2)))):
        m = re.search(pat, s, re.I)
        if m and (best is None or m.start() < best[0]):
            q, y = conv(m)
            best = (m.start(), f"{_yr(y)}Q{q}")
    return best[1] if best else None


def _quarters_named(sentence):
    """(quarter number or None, year or None) for every quarter/period named in a sentence."""
    out = []
    for m in re.finditer(r"\b(first|second|third|fourth)[- ]quarter\b(?:(?: of)?,? (20\d{2}))?", sentence, re.I):
        out.append((_QWORD[m.group(1).lower()], int(m.group(2)) if m.group(2) else None))
    for m in re.finditer(r"\b(?:([1-4])Q|Q([1-4]))[ ']?(20\d{2}|\d{2})?\b", sentence):
        out.append((int(m.group(1) or m.group(2)), _yr(m.group(3)) if m.group(3) else None))
    return out


# ── Figures ───────────────────────────────────────────────────────────────────

# Whole sentences that are not about the quarter's own reported figure.
_SKIP_SENTENCE = re.compile(
    r"\b(full[- ]year|for the (?:full )?year|year[- ]to[- ]date|ytd|first half|second half|"
    r"six[- ]months?|nine[- ]months?|twelve[- ]months?|trailing|ttm|guidance|outlook|forecast|"
    r"we expect|expected|expects|expecting|target(?:s|ed|ing)?|run[- ]rate|annual(?:ly)?|"
    r"cumulative|since inception|pro forma|would have been|excluding)\b", re.I)
# A comparison just before the figure means the figure is the comparator.
_COMPARATIVE = re.compile(
    r"\b(prior|previous|last (?:year|quarter)|a year ago|year[- ]ago|compared (?:to|with)|versus|vs\.?|"
    r"up from|down from|increased from|decreased from|declined from|rose from|fell from)\b", re.I)
_MOVEMENT = re.compile(
    r"\b(increas\w*|decreas\w*|declin\w*|expand\w*|compress\w*|contract\w*|improv\w*|widen\w*|narrow\w*|"
    r"rose|fell|grew|growth|up|down|higher|lower|dropped|climbed|jumped)\b", re.I)

_USD = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(billion|bn|million|mm|mn|m)\b", re.I)
_PCT = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s?(%|percent\b|basis points\b|bps\b|bp\b)", re.I)


def _amounts(text, unit):
    """[(start, end, value)] in the metric's unit: $m for usd_m, percent for pct."""
    out = []
    if unit == "usd_m":
        for m in _USD.finditer(text):
            v = float(m.group(1).replace(",", ""))
            out.append((m.start(), m.end(), v * 1000 if m.group(2).lower() in ("billion", "bn") else v))
    else:
        for m in _PCT.finditer(text):
            v = float(m.group(1))
            out.append((m.start(), m.end(), v / 100 if m.group(2).lower().startswith("b") else v))
    return out


def _figure_after_label(sentence, label_end, unit, window=140):
    """The reported figure following a metric label, or None."""
    gap = sentence[label_end:label_end + window]
    amounts = _amounts(gap, unit)
    if not amounts:
        return None
    start, _end, value = amounts[0]
    lead = gap[:start]
    if _COMPARATIVE.search(lead):
        return None
    if _MOVEMENT.search(lead):
        # "...declined 11 basis points to 1.47%": the level is the figure after "to".
        after_to = [a for a in amounts if re.search(r"\bto\s*$", gap[:a[0]])]
        if not after_to:
            return None
        value = after_to[0][2]
    return value


def extract_prose_metrics(text, quarter, metric_specs):
    """Figures for `quarter` ("2026Q2") from transcript/release text.

    metric_specs: {key: {"unit", "bounds", "prose": [label regexes]}}.
    Returns (found {key: value}, notes {key: str}) — notes explain skips.
    """
    year, qn = int(quarter[:4]), int(quarter[-1])
    candidates = {k: [] for k in metric_specs}
    for s in sentences(normalise(text)):
        if _SKIP_SENTENCE.search(s):
            continue
        named = _quarters_named(s)
        if any(q != qn or (y is not None and y != year) for q, y in named):
            continue
        if any(int(y) != year for y in re.findall(r"\b(20\d{2})\b", s)):
            continue
        for key, spec in metric_specs.items():
            for pat in spec.get("prose", []):
                for m in re.finditer(pat, s, re.I):
                    prefix = s[max(0, m.start() - 60):m.start()]
                    if _COMPARATIVE.search(prefix):
                        continue
                    v = _figure_after_label(s, m.end(), spec["unit"])
                    lo, hi = spec["bounds"]
                    if v is not None and lo <= v <= hi:
                        candidates[key].append(round(v, 4))
    found, notes = {}, {}
    for key, vals in candidates.items():
        if not vals:
            continue
        ranked = Counter(vals).most_common()
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            notes[key] = f"ambiguous: {sorted(set(vals))}"
            continue
        found[key] = ranked[0][0]
    return found, notes


# ── Finding documents on a company's site ─────────────────────────────────────

def discover_links(html, base_url, pattern):
    """Absolute URLs of hrefs matching `pattern`, in page order, de-duplicated."""
    seen, out = set(), []
    for href in re.findall(r"""href\s*=\s*["']([^"'#]+)["']""", html, re.I):
        href = htmllib.unescape(href).strip()
        if re.search(pattern, href, re.I):
            url = urljoin(base_url, href)
            if url not in seen:
                seen.add(url)
                out.append(url)
    return out
