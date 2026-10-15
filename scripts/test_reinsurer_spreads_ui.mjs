/* Checks for the PE reinsurer page's series, changes and formatting.
   Run: node scripts/test_reinsurer_spreads_ui.mjs                     */

import {
  quarterIndex, quarterFromIndex, quarterLabel, quarterAxis, summarizeMetric,
  lineScale, formatValue, formatAxisValue, formatChange, tableRows, buildReinsurerView, groupNotCovered,
} from "../src/reinsurerSpreads.js";

let pass = 0, fail = 0;
function check(name, cond, got, want) {
  if (cond) { pass++; console.log(`  ok   ${name}`); }
  else { fail++; console.log(`  FAIL ${name}\n         got  ${JSON.stringify(got)}\n         want ${JSON.stringify(want)}`); }
}
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const pt = (quarter, value, extra = {}) => ({ quarter, value, filed: "2026-08-05", form: "8-K", url: `u/${quarter}`, ...extra });
const ATHENE_SRE = ["2024Q2", "2024Q3", "2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"];
const data = {
  updated: "2026-10-13T06:00:00Z",
  note: "Company-defined non-GAAP measures; not comparable across companies.",
  companies: [
    { key: "athene", name: "Athene", owner: "Apollo", status: "ok", note: null, edgar_url: "e/athene",
      metrics: {
        earnings: { label: "Spread related earnings (SRE)", unit: "usd_m",
          points: ATHENE_SRE.map((q, i) => pt(q, [712, 855, 838, 804, 820, 872, 850, 719, 877][i],
            q === "2025Q1" ? { revised_from: 816 } : {})) },
        spread: { label: "Net investment spread", unit: "pct",
          points: [pt("2025Q2", 1.62), pt("2025Q3", 1.66), pt("2025Q4", 1.60), pt("2026Q1", 1.31), pt("2026Q2", 1.58, { filed: "2026-08-06" })] },
      } },
    // Lags a quarter and skipped one: no YoY, a gap on the axis.
    { key: "global_atlantic", name: "Global Atlantic", owner: "KKR", status: "ok", note: "RuntimeError: SEC refused the request (403)",
      metrics: { earnings: { label: "Insurance operating earnings", unit: "usd_m",
        points: [pt("2025Q2", 280.1), pt("2025Q4", 310), pt("2026Q1", 301.23)] } } },
    { key: "brookfield_ws", name: "Brookfield Wealth Solutions", owner: "Brookfield", status: "no_data", note: null,
      metrics: { earnings: { label: "Distributable operating earnings (DOE)", unit: "usd_m", points: [] } } },
    { key: "x", name: "Errored", owner: "X", status: "error", note: "URLError: timed out",
      metrics: { earnings: { label: "E", unit: "usd_m", points: [] } } },
  ],
  not_covered: [{ name: "Prismic Re", owner: "Prudential / Warburg Pincus", detail: "No Prismic earnings or spread." }],
};

console.log("\nquarters");
check("index round-trips", quarterFromIndex(quarterIndex("2026Q2")) === "2026Q2", quarterFromIndex(quarterIndex("2026Q2")), "2026Q2");
check("Q1 minus one is last year's Q4", quarterFromIndex(quarterIndex("2026Q1") - 1) === "2025Q4", "—", "2025Q4");
check("filing-style label", quarterLabel("2026Q2") === "2Q'26", quarterLabel("2026Q2"), "2Q'26");
check("bad key ⇒ null index", quarterIndex("2026-06-30") === null, quarterIndex("2026-06-30"), null);
const axis = quarterAxis(data.companies);
check("shared axis: 12 quarters ending at the newest disclosed", axis.length === 12 && axis[11] === "2026Q2" && axis[0] === "2023Q3",
  [axis.length, axis[0], axis[11]], [12, "2023Q3", "2026Q2"]);
check("no data ⇒ empty axis", quarterAxis([]).length === 0 && quarterAxis(undefined).length === 0, "—", 0);

console.log("\nsummary and changes");
const sre = summarizeMetric(data.companies[0].metrics.earnings, axis);
check("latest point", sre.latest.quarter === "2026Q2" && sre.latest.value === 877, sre.latest, { quarter: "2026Q2", value: 877 });
check("QoQ in $m and %", eq(sre.qoq, { abs: 158, pct: 22, from: "2026Q1" }), sre.qoq, { abs: 158, pct: 22, from: "2026Q1" });
check("YoY against the same quarter last year", eq(sre.yoy, { abs: 57, pct: 7, from: "2025Q2" }), sre.yoy, { abs: 57, pct: 7, from: "2025Q2" });
check("restated quarter listed", eq(sre.restated, ["2025Q1"]), sre.restated, ["2025Q1"]);
check("series carries the original figure", sre.series.find(s => s.quarter === "2025Q1").revisedFrom === 816, "—", 816);
check("undisclosed quarters are null, not 0", sre.series[0].value === null && sre.series.filter(s => s.value != null).length === 9,
  sre.series.map(s => s.value), "3 nulls then 9 values");
const spread = summarizeMetric(data.companies[0].metrics.spread, axis);
check("spread change in bp", spread.qoq.bp === 27 && spread.yoy.bp === -4, [spread.qoq, spread.yoy], [27, -4]);
const ga = summarizeMetric(data.companies[1].metrics.earnings, axis);
check("lagging company: gap at the newest quarter", ga.series[11].value === null && ga.latest.quarter === "2026Q1", ga.latest, "2026Q1");
check("missing YoY quarter ⇒ null, never a further-back stand-in", ga.yoy === null, ga.yoy, null);
check("QoQ from the quarter before", ga.qoq.abs === -8.8, ga.qoq, -8.8);

console.log("\nformatting");
check("$m under 100 keeps a decimal", formatValue(85.25, "usd_m") === "$85.3m", formatValue(85.25, "usd_m"), "$85.3m");
check("$m with thousands separator", formatValue(1624, "usd_m") === "$1,624m", formatValue(1624, "usd_m"), "$1,624m");
check("negative $m", formatValue(-12, "usd_m") === "−$12.0m", formatValue(-12, "usd_m"), "−$12.0m");
check("spread %", formatValue(1.5, "pct") === "1.50%", formatValue(1.5, "pct"), "1.50%");
check("missing value", formatValue(null, "pct") === "—", formatValue(null, "pct"), "—");
const c1 = formatChange(sre.qoq, "usd_m");
check("earnings change string", c1.text === "+$158m (+22.0%)" && c1.dir === 1, c1, "+$158m (+22.0%)");
const c2 = formatChange(spread.yoy, "pct");
check("spread change string", c2.text === "−4bp" && c2.dir === -1, c2, "−4bp");
check("no change ⇒ null", formatChange(null, "pct") === null, "—", null);
check("small earnings change keeps a decimal", formatChange(ga.qoq, "usd_m").text === "−$8.8m (−2.8%)", formatChange(ga.qoq, "usd_m"), "−$8.8m (−2.8%)");
check("axis labels: whole $m, spread 2dp", formatAxisValue(0, "usd_m") === "$0m" && formatAxisValue(1000, "usd_m") === "$1,000m"
  && formatAxisValue(1.2, "pct") === "1.20%", [formatAxisValue(0, "usd_m"), formatAxisValue(1000, "usd_m")], ["$0m", "$1,000m"]);
const evenTicks = s => s.ticks.every((t, i) => i === 0 || Math.abs((t - s.ticks[i - 1]) - (s.ticks[1] - s.ticks[0])) < 1e-9);
const sc = lineScale([1.72, 1.31, 1.58, null]);
check("spread scale: round, even ticks spanning the domain", eq(sc, { domain: [1.2, 1.8], ticks: [1.2, 1.4, 1.6, 1.8] }), sc, { domain: [1.2, 1.8], ticks: [1.2, 1.4, 1.6, 1.8] });
check("data sits inside the domain", sc.domain[0] < 1.31 && sc.domain[1] > 1.72, sc.domain, "contains 1.31..1.72");
const flat = lineScale([1.6, 1.6]);
check("flat line still gets 0.2pp of height", flat.domain[1] - flat.domain[0] >= 0.2 - 1e-9 && evenTicks(flat), flat, ">= 0.2, even ticks");
const low = lineScale([0.05, 0.08]);
check("scale never below zero", low.domain[0] === 0 && low.ticks[0] === 0 && evenTicks(low), low, "starts at 0");
const wide = lineScale([0.4, 3.9]);
check("wide range stays at five ticks or fewer", wide.ticks.length <= 5 && evenTicks(wide) && wide.domain[1] >= 3.9, wide, "<= 5 ticks");
check("no values ⇒ a usable default", lineScale([null]).ticks.length > 1, lineScale([null]), "default");

console.log("\nview");
const view = buildReinsurerView(data);
check("companies kept in file order", view.companies.map(c => c.key).join() === "athene,global_atlantic,brookfield_ws,x", "—", "file order");
const [ath, gav, bws, err] = view.companies;
check("metrics in file order", ath.metrics.map(m => m.key).join() === "earnings,spread", "—", "earnings,spread");
check("latest filing is the newest filed date", ath.latestFiling.filed === "2026-08-06", ath.latestFiling, "2026-08-06");
check("failed refresh with cache ⇒ ok but stale, with the reason", gav.status === "ok" && gav.stale && gav.message.includes("403"),
  [gav.status, gav.stale, gav.message], "ok/stale/403");
check("no data ⇒ explanatory message", bws.status === "no_data" && /scheduled/.test(bws.message), bws.message, "no data message");
check("error without cache ⇒ error with the reason", err.status === "error" && err.message.includes("timed out"), err.message, "timed out");
check("not-covered list passed through", view.notCovered[0].names[0] === "Prismic Re", "—", "Prismic Re");
const nc = groupNotCovered([{ name: "Prismic Re", detail: "Own story." }, { name: "A", detail: "Private." }, { name: "B", detail: "Private." }]);
check("shared descriptions collapse into one line, file order kept", eq(nc, [{ names: ["Prismic Re"], detail: "Own story." }, { names: ["A", "B"], detail: "Private." }]),
  nc, "[Prismic Re], [A, B]");
check("empty file ⇒ empty view", buildReinsurerView(undefined).companies.length === 0, "—", 0);

console.log("\ntable");
const rows = tableRows(ath);
check("newest first, undisclosed quarters skipped", rows.length === 9 && rows[0].quarter === "2026Q2" && rows[8].quarter === "2024Q2",
  [rows.length, rows[0].quarter, rows[8].quarter], [9, "2026Q2", "2024Q2"]);
check("one cell per metric, missing shown as dash", eq(rows[8].values.map(v => v.text), ["$712m", "—"]), rows[8].values, ["$712m", "—"]);
check("restated cell shows the original", rows.find(r => r.quarter === "2025Q1").values[0].revisedFrom === "$816m", "—", "$816m");
check("row links the newest filing for that quarter", rows[0].filed === "2026-08-06" && rows[0].url === "u/2026Q2", rows[0], "2026-08-06");

console.log("\nfallback sources");
const fbData = {
  companies: [{
    key: "brookfield_ws", name: "BWS", owner: "Brookfield", status: "ok", note: "RuntimeError: SEC refused the request (403)",
    fallback_source: "BWS results release (bnt.brookfield.com)", fallback_note: null,
    metrics: { earnings: { label: "DOE", unit: "usd_m", points: [
      pt("2026Q1", 438, { filed: "2026-05-08", form: "6-K" }),
      pt("2026Q2", 488, { filed: "2026-10-15", form: "BWS results release", source: "release", url: "r/q2" }),
    ] } },
  }, { key: "global_atlantic", name: "GA", owner: "KKR", status: "ok", note: null, fallback_source: null,
       fallback_note: "KKR doesn't post call transcripts on its own site.",
       metrics: { earnings: { label: "E", unit: "usd_m", points: [pt("2026Q2", 288, { source: "sec" })] } } }],
};
const fv = buildReinsurerView(fbData);
const [fb, kkr] = fv.companies;
const fm = fb.metrics[0];
check("series carries each point's source", fm.series[11].source === "release" && fm.series[10].source === "sec" && fm.series[0].source === null,
  fm.series.slice(-2).map(x => x.source), ["sec", "release"]);
check("fallback quarters listed", eq(fm.fallbackQuarters, ["2026Q2"]), fm.fallbackQuarters, ["2026Q2"]);
check("latest figure may come from the release", fm.latest.quarter === "2026Q2" && fm.latest.source === "release", fm.latest, "release");
check("'latest filing' link only points at SEC filings", fb.latestFiling.quarter === "2026Q1", fb.latestFiling, "2026Q1 6-K");
check("message explains the fallback, with the SEC error", fb.usesFallback && /couldn't be read/.test(fb.message) && fb.message.includes("403")
  && fb.message.includes("results release"), fb.message, "fallback message");
check("fallback source and KKR's note passed through", fb.fallbackSource.startsWith("BWS results release") && kkr.fallbackNote.includes("transcripts")
  && !kkr.usesFallback && kkr.message === null, [fb.fallbackSource, kkr.fallbackNote], "passed through");
const frows = tableRows(fb);
check("table names the source of each row", frows[0].sourceText === "results release (read 2026-10-15)" && frows[1].sourceText === "6-K 2026-05-08",
  frows.map(r => r.sourceText), ["results release (read 2026-10-15)", "6-K 2026-05-08"]);

console.log(`\n${pass} passed, ${fail} failed\n`);
process.exit(fail ? 1 : 0);
