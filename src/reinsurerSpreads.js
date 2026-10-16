/* PE-backed life reinsurers: the per-company series, latest values and
   changes the page shows, built from data/reinsurer_spreads.json (written by
   scripts/fetch_reinsurer_spreads.py from SEC filings). Pure, so it is
   testable without a browser (scripts/test_reinsurer_spreads_ui.mjs);
   rendering lives in ReinsurerSpreads.jsx. */

export const QUARTERS_SHOWN = 12;

// Where a figure came from. SEC filings are the primary source; the others
// fill quarters a filing couldn't supply and are replaced once it is read.
export const SOURCE_TEXT = {
  sec: "SEC filing",
  call: "earnings call transcript",
  release: "results release",
};
const sourceOf = p => (p ? p.source || "sec" : null);

const QRE = /^(\d{4})Q([1-4])$/;
const isNum = v => typeof v === "number" && Number.isFinite(v);

/** "2026Q2" -> 8105 (a running quarter count), so quarters subtract cleanly. */
export function quarterIndex(q) {
  const m = QRE.exec(q || "");
  return m ? Number(m[1]) * 4 + Number(m[2]) - 1 : null;
}
export const quarterFromIndex = i => `${Math.floor(i / 4)}Q${(i % 4) + 1}`;
/** "2026Q2" -> "2Q'26", the way the filings write it. */
export function quarterLabel(q) {
  const m = QRE.exec(q || "");
  return m ? `${m[2]}Q'${m[1].slice(2)}` : q;
}

/** One quarter axis shared by every company, ending at the newest quarter
    anyone has disclosed, so the small multiples line up in time. A company
    that has not reported that quarter yet shows a gap, not a shifted axis. */
export function quarterAxis(companies = [], n = QUARTERS_SHOWN) {
  let last = null;
  for (const c of companies)
    for (const m of Object.values(c.metrics || {}))
      for (const p of m.points || []) {
        const i = quarterIndex(p.quarter);
        if (i != null && isNum(p.value) && (last == null || i > last)) last = i;
      }
  if (last == null) return [];
  return Array.from({ length: n }, (_, k) => quarterFromIndex(last - n + 1 + k));
}

// Change from `prior` to `cur` in the metric's own terms: basis points for a
// spread, $m plus percent for earnings.
function change(cur, prior, unit) {
  if (!cur || !prior || !isNum(cur.value) || !isNum(prior.value)) return null;
  const d = cur.value - prior.value;
  if (unit === "pct") return { bp: Math.round(d * 100), from: prior.quarter };
  return {
    abs: Math.round(d * 10) / 10,
    pct: prior.value ? Math.round((d / Math.abs(prior.value)) * 1000) / 10 : null,
    from: prior.quarter,
  };
}

/** Series on the shared axis plus the latest point and its QoQ / YoY change.
    QoQ and YoY compare against the quarter exactly 1 and 4 back; if that
    quarter was not disclosed the change is null rather than reaching further. */
export function summarizeMetric(metric, axis) {
  const byQ = {};
  for (const p of metric?.points || []) if (QRE.test(p.quarter) && isNum(p.value)) byQ[p.quarter] = p;
  const quarters = Object.keys(byQ).sort();
  const latest = quarters.length ? byQ[quarters[quarters.length - 1]] : null;
  const back = n => latest && byQ[quarterFromIndex(quarterIndex(latest.quarter) - n)];
  const unit = metric?.unit;
  return {
    series: axis.map(q => ({
      quarter: q, label: quarterLabel(q), value: byQ[q] ? byQ[q].value : null,
      filed: byQ[q]?.filed ?? null, form: byQ[q]?.form ?? null, url: byQ[q]?.url ?? null,
      revisedFrom: isNum(byQ[q]?.revised_from) ? byQ[q].revised_from : null,
      source: sourceOf(byQ[q]),
    })),
    latest,
    qoq: change(latest, back(1), unit),
    yoy: change(latest, back(4), unit),
    restated: quarters.filter(q => isNum(byQ[q].revised_from) && axis.includes(q)),
    fallbackQuarters: quarters.filter(q => sourceOf(byQ[q]) !== "sec" && axis.includes(q)),
    count: quarters.filter(q => axis.includes(q)).length,
  };
}

/** Y-axis for a spread line: the padded data range, at least 0.2pp tall so
    a flat series does not read as a big move, snapped to evenly spaced
    round ticks (at most ~5). Bars always start at zero and do not use this. */
export function lineScale(values, maxTicks = 5) {
  const v = values.filter(isNum);
  if (!v.length) return { domain: [0, 1], ticks: [0, 0.5, 1] };
  let lo = Math.min(...v), hi = Math.max(...v);
  const pad = Math.max((hi - lo) * 0.1, 0.05);
  lo -= pad; hi += pad;
  if (hi - lo < 0.2) { const mid = (lo + hi) / 2; lo = mid - 0.1; hi = mid + 0.1; }
  lo = Math.max(0, lo); hi = Math.max(hi, lo + 0.2);
  const r = x => Math.round(x * 1000) / 1000;
  const step = [0.05, 0.1, 0.2, 0.25, 0.5, 1, 2].find(s => (hi - lo) / s <= maxTicks - 1) ?? 5;
  const a = Math.floor(lo / step + 1e-9) * step, b = Math.ceil(hi / step - 1e-9) * step;
  const ticks = [];
  for (let k = 0; a + k * step <= b + 1e-9; k++) ticks.push(r(a + k * step));
  return { domain: [r(a), r(b)], ticks };
}

// ── Formatting ──

const thousands = v => v.toLocaleString("en-US", { maximumFractionDigits: 0 });

export function formatValue(v, unit) {
  if (!isNum(v)) return "—";
  if (unit === "pct") return `${v.toFixed(2)}%`;
  const a = Math.abs(v);
  const s = a >= 100 ? thousands(a) : a.toFixed(1);
  return `${v < 0 ? "−" : ""}$${s}m`;
}

/** Axis tick labels: whole $m (ticks are round numbers), spreads to 2dp. */
export function formatAxisValue(v, unit) {
  if (!isNum(v)) return "";
  if (unit === "pct") return `${v.toFixed(2)}%`;
  return `${v < 0 ? "−" : ""}$${thousands(Math.abs(v))}m`;
}

/** Signed change string; direction is also returned so the UI can add an arrow. */
export function formatChange(ch, unit) {
  if (!ch) return null;
  const sign = n => (n > 0 ? "+" : n < 0 ? "−" : "±");
  if (unit === "pct") return { text: `${sign(ch.bp)}${Math.abs(ch.bp)}bp`, dir: Math.sign(ch.bp) };
  const a = Math.abs(ch.abs);
  const pct = ch.pct == null ? "" : ` (${sign(ch.pct)}${Math.abs(ch.pct).toFixed(1)}%)`;
  return { text: `${sign(ch.abs)}$${a >= 10 ? thousands(a) : a.toFixed(1)}m${pct}`, dir: Math.sign(ch.abs) };
}

/** Rows for the table view, newest quarter first, quarters with no value skipped. */
export function tableRows(company) {
  const rows = [];
  const n = company.metrics[0]?.series.length || 0;
  for (let i = n - 1; i >= 0; i--) {
    const cells = company.metrics.map(m => m.series[i]);
    if (cells.every(c => c.value == null)) continue;
    const src = cells.filter(c => c.filed).sort((a, b) => (a.filed < b.filed ? 1 : -1))[0];
    rows.push({
      quarter: cells[0].quarter, label: cells[0].label,
      values: cells.map((c, k) => ({
        text: formatValue(c.value, company.metrics[k].unit),
        revisedFrom: c.revisedFrom == null ? null : formatValue(c.revisedFrom, company.metrics[k].unit),
      })),
      filed: src?.filed ?? null, form: src?.form ?? null, url: src?.url ?? null,
      source: src?.source ?? null,
      sourceText: !src ? null : src.source === "sec" ? `${src.form} ${src.filed}`
        : `${SOURCE_TEXT[src.source] || "company document"} (read ${src.filed})`,
    });
  }
  return rows;
}

/** Not-covered entries with the same description collapse into one line
    (names listed together); entries with their own story stay separate,
    in file order of each group's first entry. */
export function groupNotCovered(items = []) {
  const groups = [];
  const byDetail = new Map();
  for (const it of items) {
    const g = byDetail.get(it.detail);
    if (g) g.names.push(it.name);
    else { const ng = { names: [it.name], detail: it.detail || null }; byDetail.set(it.detail, ng); groups.push(ng); }
  }
  return groups;
}

const STATUS_TEXT = {
  ok: null,
  no_data: "No figures read from SEC filings yet. The SEC fetch runs with each scheduled data refresh.",
  error: "The SEC fetch failed for this company at the last refresh and nothing is cached yet.",
};

// ── Reasons (data/reinsurer_commentary.json, from the earnings call review) ──

export const TONE_TEXT = { good: "Good", average: "Average", bad: "Bad" };
// Display order for companies the SEC file doesn't carry yet.
const COMPANY_ORDER = ["athene", "global_atlantic", "brookfield_ws", "corebridge", "fg"];

/** One company's calls from the review: oldest first, each with its quarter
    label, sentiment meter and tagged lines; plus metric, coverage and the
    latest watch-list entry. Null when the review doesn't cover the company. */
export function commentaryFor(commentary, key) {
  const c = commentary?.companies?.[key];
  if (!c) return null;
  const calls = Object.entries(c.quarters || {})
    .filter(([q]) => QRE.test(q))
    .sort(([a], [b]) => (a < b ? -1 : 1))
    .map(([quarter, v]) => ({
      quarter, label: quarterLabel(quarter), date: v.date || null, read: v.read || null,
      sources: v.sources || [], lines: v.lines || [], meter: v.meter || null,
    }));
  return {
    heading: c.heading || null, metric: c.metric || null, coverage: c.coverage || null, watch: c.watch || null,
    calls, byQuarter: Object.fromEntries(calls.map(x => [x.quarter, x])),
    latest: calls.length ? calls[calls.length - 1] : null,
  };
}

/** Quarter the reasons panel opens on: the newest quarter that has both a
    figure and commentary; else the newest commented quarter. */
export function defaultReasonQuarter(company) {
  const r = company.reasons;
  if (!r?.calls.length) return null;
  const withData = new Set(company.metrics.flatMap(m => m.series.filter(p => p.value != null).map(p => p.quarter)));
  const both = r.calls.filter(c => withData.has(c.quarter));
  return (both.length ? both[both.length - 1] : r.latest).quarter;
}

/** Everything the page renders, in display order. Companies the review
    covers but the SEC file doesn't carry yet still get a card (reasons only). */
export function buildReinsurerView(data, commentary) {
  const companies = [...(data?.companies || [])];
  for (const key of Object.keys(commentary?.companies || {})) {
    if (companies.some(c => c.key === key)) continue;
    const heading = commentary.companies[key].heading || key;
    companies.push({ key, name: heading.split(/\s+[—(]/)[0].trim(), owner: null, status: "no_data", metrics: {} });
  }
  const rank = k => (COMPANY_ORDER.includes(k) ? COMPANY_ORDER.indexOf(k) : COMPANY_ORDER.length);
  companies.sort((a, b) => rank(a.key) - rank(b.key));
  const axis = quarterAxis(companies);
  return {
    updated: data?.updated || null,
    note: data?.note || null,
    axis,
    notCovered: groupNotCovered(data?.not_covered || []),
    review: commentary?.source ? { ...commentary.source, summary: commentary.summary || [] } : null,
    companies: companies.map(c => {
      const metrics = Object.entries(c.metrics || {}).map(([key, m]) => ({
        key, label: m.label || key, unit: m.unit, ...summarizeMetric(m, axis),
      }));
      const latestFiling = metrics.flatMap(m => m.series).filter(p => p.filed && p.source === "sec")
        .sort((a, b) => (a.filed < b.filed ? 1 : -1))[0] || null;
      const hasData = metrics.some(m => m.latest);
      const usesFallback = metrics.some(m => m.fallbackQuarters.length > 0);
      const fallbackKinds = [...new Set(metrics.flatMap(m => m.series).filter(p => p.source && p.source !== "sec")
        .map(p => SOURCE_TEXT[p.source] || "company document"))];
      let message = null;
      if (!hasData) message = [STATUS_TEXT[c.status === "error" ? "error" : "no_data"], c.note].filter(Boolean).join(" ");
      else if (c.note && usesFallback)
        message = `SEC filings couldn't be read at the last refresh (${c.note}). Quarters without a filing are filled from the ${fallbackKinds.join(" / ")} and marked as such.`;
      else if (c.note) message = `Last refresh failed (${c.note}); showing figures collected earlier.`;
      return {
        key: c.key, name: c.name, owner: c.owner, source: c.source, definition: c.definition, scope: c.scope || null,
        edgarUrl: c.edgar_url, metrics, latestFiling, hasData, usesFallback, fallbackKinds,
        fallbackSource: c.fallback_source || null, fallbackNote: c.fallback_note || null,
        status: hasData ? "ok" : c.status === "error" ? "error" : "no_data",
        // A failed run keeps the cached figures; say so instead of hiding it.
        stale: hasData && !!c.note,
        message,
        reasons: commentaryFor(commentary, c.key),
      };
    }),
  };
}
