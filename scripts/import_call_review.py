#!/usr/bin/env python3
"""Turn the weekly "PE Life Reinsurers — Earnings Call Review" document into
data/reinsurer_commentary.json, the "why it moved" layer of the PE
Reinsurers page.

The review is written by a scheduled routine (one section per company, one
sub-section per earnings call, 5-10 tagged lines and a sentiment meter per
call). The data pipeline can't read it (it's a private Claude doc), so this
importer runs on an exported copy whenever the review is refreshed:

    python scripts/import_call_review.py <export.json|export.xml> [--url <doc link>] [--mdna <doc link>]

<export> is the doc's prose read (the JSON a docs read returns, with
data.xml) or the bare <doc> XML.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

OUT = Path(__file__).parent.parent / "data" / "reinsurer_commentary.json"

# Section heading -> company key used by data/reinsurer_spreads.json.
COMPANY_KEYS = [
    (r"athene|apollo", "athene"),
    (r"kkr|global atlantic", "global_atlantic"),
    (r"brookfield", "brookfield_ws"),
    (r"corebridge", "corebridge"),
    (r"f&g|f&amp;g", "fg"),
]
TONES = {"🟢": "good", "🟡": "average", "🔴": "bad"}
_QUARTER = re.compile(r"\bQ([1-4])\s*FY\s*(\d{4})\b", re.I)


# ── Document -> blocks ────────────────────────────────────────────────────────

def _inline(el):
    """Text of a block with links kept as (text, href) runs."""
    runs = []
    for node in el.iter():
        if node.tag == "text":
            link = node.find("link")
            txt = "".join(node.itertext())
            runs.append((txt, link.get("href") if link is not None else None))
        elif node.tag == "date":
            runs.append((node.get("value") or "", None))
    return runs


def blocks(xml):
    """[(kind, level, runs)] in document order; kind is heading/para/item/row."""
    root = ET.fromstring(xml)
    out = []
    for el in root:
        if el.tag == "paragraph":
            h = el.get("heading")
            out.append(("heading" if h else "para", int(h) if h else 0, _inline(el)))
        elif el.tag == "list":
            for li in el.findall("listItem"):
                out.append(("item", 0, _inline(li)))
        elif el.tag == "table":
            for row in el.findall("row"):
                out.append(("row", 0, [run for cell in row.findall("cell") for run in _inline(cell) + [(" | ", None)]]))
    return out


def plain(runs):
    return " ".join("".join(t for t, _ in runs).split())


# ── Parsing ───────────────────────────────────────────────────────────────────

def company_key(heading):
    h = heading.lower()
    return next((k for pat, k in COMPANY_KEYS if re.search(pat, h)), None)


def parse_line(text):
    """'🟢 Good [Spread] Net spread 166bp…' -> {tone, theme, text}."""
    m = re.match(r"^\s*(🟢|🟡|🔴)\s*(?:Good|Average|Bad)?\s*(?:\[([^\]]+)\])?\s*(.*)$", text)
    if not m:
        return None
    return {"tone": TONES[m.group(1)], "theme": (m.group(2) or "").strip(), "text": m.group(3).strip()}


def parse_meter(text):
    """'Meter: G4 / B0 / N8 → +0.50 (Good), ↑ (record SRE…). Not discussed: …'"""
    m = re.search(r"G(\d+)\s*/\s*B(\d+)\s*/\s*N(\d+)\s*→\s*([+\-−]?\d+(?:\.\d+)?)\s*\((Good|Average|Bad)\)", text)
    if not m:
        return None
    # Drop the routine's bookkeeping asides, e.g. "(Count corrected from the research notes.)".
    rest = re.sub(r"\s*\([^)]*research notes[^)]*\)\.?", "", text[m.end():]).strip(" ,.")
    arrow = rest[:1] if rest[:1] in ("↑", "↓", "→") else None
    return {"good": int(m.group(1)), "bad": int(m.group(2)), "n": int(m.group(3)),
            "score": float(m.group(4).replace("−", "-")), "label": m.group(5),
            "arrow": arrow, "note": (rest[1:] if arrow else rest).strip(" ,.") or None}


def parse_call_heading(runs):
    """'Q2 FY2026 — 4 Aug 2026 — [transcript](url), [8-K](url) — transcript and release read'."""
    text = plain(runs)
    m = _QUARTER.search(text)
    if not m:
        return None
    parts = [p.strip() for p in re.split(r"\s+—\s+", text)]
    sources = [{"label": t.strip(), "url": u} for t, u in runs if u]
    read = parts[-1] if len(parts) >= 3 and not any(s["label"] == parts[-1] for s in sources) else None
    return {"quarter": f"{m.group(2)}Q{m.group(1)}", "date": parts[1] if len(parts) > 1 else None,
            "sources": sources, "read": read}


def parse_review(xml):
    bl = blocks(xml)
    doc = {"title": None, "as_of": None, "summary": [], "companies": {}}
    section, company, call = None, None, None
    for kind, level, runs in bl:
        text = plain(runs)
        if kind == "heading" and level == 1:
            doc["title"] = text
            continue
        if kind == "para" and doc["as_of"] is None and re.match(r"^As of \d{4}-\d{2}-\d{2}", text):
            doc["as_of"] = text[6:16]
            continue
        if kind == "heading" and level == 2:
            call = None
            key = company_key(text) if re.match(r"^\d+\.", text) else None
            if key:
                section, company = "company", key
                metric = re.search(r"\(metric:\s*([^)]+)\)", text)
                doc["companies"][key] = {"heading": re.sub(r"^\d+\.\s*", "", text),
                                         "metric": metric.group(1).strip() if metric else None,
                                         "coverage": None, "watch": None, "quarters": {}}
            elif text.lower().startswith("executive summary"):
                section, company = "summary", None
            elif text.lower().startswith("watch list"):
                section, company = "watch", None
            else:
                section, company = None, None
            continue
        if section == "summary" and kind == "item":
            doc["summary"].append(text)
        elif section == "watch" and kind == "item":
            name, _, rest = text.partition(":")
            key = company_key(name)
            if key and key in doc["companies"]:
                doc["companies"][key]["watch"] = rest.strip()
        elif section == "company":
            entry = doc["companies"][company]
            if kind == "heading" and level == 3:
                call = parse_call_heading(runs)
                if call:
                    entry["quarters"][call["quarter"]] = {**{k: v for k, v in call.items() if k != "quarter"},
                                                          "lines": [], "meter": None}
            elif kind == "para" and text.startswith("Coverage:") and call is None:
                entry["coverage"] = text[len("Coverage:"):].strip()
            elif call and kind == "item":
                line = parse_line(text)
                if line:
                    entry["quarters"][call["quarter"]]["lines"].append(line)
            elif call and kind == "para" and text.startswith("Meter:"):
                entry["quarters"][call["quarter"]]["meter"] = parse_meter(text)
    return doc


def load_xml(path):
    raw = Path(path).read_text()
    if raw.lstrip().startswith("<"):
        return raw
    data = json.loads(raw)
    data = data.get("data", data)
    return data["xml"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export")
    ap.add_argument("--url", help="link to the earnings call review doc")
    ap.add_argument("--mdna", help="link to the MD&A commentary review doc")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    review = parse_review(load_xml(args.export))
    counts = {k: len(c["quarters"]) for k, c in review["companies"].items()}
    if not counts or min(counts.values()) == 0:
        sys.exit(f"refusing to write: a company has no calls parsed ({counts})")
    out = {"source": {"title": review["title"], "as_of": review["as_of"], "url": args.url,
                      "mdna_url": args.mdna, "kind": "earnings call review"},
           "summary": review["summary"], "companies": review["companies"]}
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {args.out}: as of {review['as_of']}, calls per company {counts}")


if __name__ == "__main__":
    main()
