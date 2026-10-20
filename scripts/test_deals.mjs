/* Checks for the Deals page's vetting rules, filters and formatting, and
   vets the real data/deals.json: any entry without a primary source, with a
   wrapped or non-https link, or with inconsistent dates fails the run.
   Run: node scripts/test_deals.mjs                                       */

import { readFileSync } from "node:fs";
import {
  validateDeal, vetDeals, isIsoDate, lastActivity, formatDate, formatUsdBn, statusLine,
  dealStats, buildDealsView, recentDeals, partiesLine, RECHECK_DAYS,
} from "../src/deals.js";

let pass = 0, fail = 0;
function check(name, cond, got, want) {
  if (cond) { pass++; console.log(`  ok   ${name}`); }
  else { fail++; console.log(`  FAIL ${name}\n         got  ${JSON.stringify(got)}\n         want ${JSON.stringify(want)}`); }
}
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const has = (problems, text) => problems.some(p => p.includes(text));

const deal = (over = {}) => ({
  id: "acme-cedant-2026", title: "Acme reinsures a block", type: "block_reinsurance", status: "closed",
  announced: "2026-02-01", closed: "2026-03-01", region: "US", summary: "Acme Re takes a block.",
  parties: [{ name: "Acme Re", role: "reinsurer" }, { name: "Cedant Life", role: "cedant" }],
  size: { usd_bn: 2.5, basis: "reserves", text: "$2.5bn reserves" },
  sources: [
    { label: "Release", publisher: "Acme Re", kind: "primary", date: "2026-02-01", url: "https://acme.example/release" },
    { label: "Story", publisher: "Trade Press", kind: "secondary", url: "https://press.example/story" },
  ],
  verified: "2026-10-01",
  ...over,
});

console.log("\nvetting rules");
check("a complete deal passes", validateDeal(deal()).length === 0, validateDeal(deal()), []);
{
  const p = validateDeal(deal({ sources: [{ label: "Story", publisher: "Trade Press", kind: "secondary", url: "https://press.example/s" }] }));
  check("coverage alone is not enough: needs a primary source", has(p, "primary source"), p, "needs a primary source");
}
check("no sources at all", has(validateDeal(deal({ sources: [] })), "at least one source"), validateDeal(deal({ sources: [] })), "needs at least one source");
{
  const g = validateDeal(deal({ sources: [{ label: "R", publisher: "P", kind: "primary", url: "https://news.google.com/rss/articles/abc" }] }));
  check("Google News redirect links are refused", has(g, "news.google.com"), g, "links via news.google.com");
  const a = validateDeal(deal({ sources: [{ label: "R", publisher: "P", kind: "primary", url: "https://archive.ph/https://x.example" }] }));
  check("archive wrappers are refused", has(a, "archive.ph"), a, "links via archive.ph");
  const h = validateDeal(deal({ sources: [{ label: "R", publisher: "P", kind: "primary", url: "http://acme.example/r" }] }));
  check("plain http is refused", has(h, "https"), h, "must use https");
  const n = validateDeal(deal({ sources: [{ label: "R", publisher: "P", kind: "primary", url: "not a url" }] }));
  check("malformed URL is refused", has(n, "valid URL"), n, "is not a valid URL");
}
{
  const s = deal().sources[0];
  const p = validateDeal(deal({ sources: [s, { ...s, label: "Again" }] }));
  check("the same URL twice is flagged", has(p, "repeats a URL"), p, "repeats a URL");
}
check("source kind must be primary or secondary", has(validateDeal(deal({ sources: [{ ...deal().sources[0], kind: "blog" }] })), "kind"), "—", "kind error");
check("closed without a closed date", has(validateDeal(deal({ closed: undefined })), "needs a closed date"), "—", "needs a closed date");
check("pending with a closed date", has(validateDeal(deal({ status: "pending" })), "only a closed deal"), "—", "only a closed deal has a closed date");
check("pending without a closed date passes", validateDeal(deal({ status: "pending", closed: undefined })).length === 0,
  validateDeal(deal({ status: "pending", closed: undefined })), []);
check("terminated needs its date", has(validateDeal(deal({ status: "terminated", closed: undefined })), "terminated date"), "—", "terminated date");
check("closing before the announcement is allowed (effective-dated deals)",
  validateDeal(deal({ announced: "2025-08-06", closed: "2025-08-01" })).length === 0, "—", []);
check("dates after the verified check are refused", has(validateDeal(deal({ closed: "2026-11-01" })), "after the verified date"), "—", "after the verified date");
check("milestone after the verified check is refused",
  has(validateDeal(deal({ milestones: [{ date: "2026-12-01", event: "x" }] })), "milestone 1"), "—", "milestone 1 error");
check("impossible calendar date", !isIsoDate("2026-02-30") && isIsoDate("2024-02-29"), [isIsoDate("2026-02-30"), isIsoDate("2024-02-29")], [false, true]);
check("bad announced date", has(validateDeal(deal({ announced: "July 2026" })), "announced"), "—", "announced error");
check("unknown type and status", has(validateDeal(deal({ type: "rumour", status: "talks" })), "unknown type") &&
  has(validateDeal(deal({ type: "rumour", status: "talks" })), "unknown status"), "—", "both flagged");
check("size needs a known basis", has(validateDeal(deal({ size: { usd_bn: 1, basis: "vibes", text: "$1bn" } })), "basis"), "—", "basis error");
check("size.usd_bn must be positive", has(validateDeal(deal({ size: { usd_bn: -1, basis: "capital", text: "x" } })), "usd_bn"), "—", "usd_bn error");
check("undisclosed size (null) passes", validateDeal(deal({ size: null })).length === 0, "—", []);
check("size without a USD figure passes", validateDeal(deal({ size: { basis: "purchase price", text: "£5.7bn" } })).length === 0, "—", []);
check("parties need name and role", has(validateDeal(deal({ parties: [{ name: "X" }] })), "party 1"), "—", "party 1 error");
check("id must be kebab-case", has(validateDeal(deal({ id: "Acme Deal" })), "id"), "—", "id error");

console.log("\nvetDeals");
{
  const v = vetDeals({ deals: [deal(), deal({ id: "dup" }), deal({ id: "dup" }), deal({ id: "bad", sources: [] })] });
  check("vetted deals kept, bad ones rejected with reasons", v.deals.length === 1 && v.rejected.length === 3, [v.deals.length, v.rejected.length], [1, 3]);
  check("duplicate ids reject every copy", v.rejected.filter(r => r.id === "dup").length === 2, v.rejected.map(r => r.id), ["dup", "dup", "bad"]);
  check("empty or missing file ⇒ nothing", vetDeals(null).deals.length === 0 && vetDeals({}).rejected.length === 0, "—", 0);
}

console.log("\nformatting");
check("date", formatDate("2026-07-30") === "30 Jul 2026", formatDate("2026-07-30"), "30 Jul 2026");
check("bad date", formatDate("soon") === "—", formatDate("soon"), "—");
check("$bn with a decimal", formatUsdBn(6.3) === "$6.3bn", formatUsdBn(6.3), "$6.3bn");
check("$bn whole above 10", formatUsdBn(32) === "$32bn", formatUsdBn(32), "$32bn");
check("under $1bn in $m", formatUsdBn(0.625) === "$625m", formatUsdBn(0.625), "$625m");
check("missing figure", formatUsdBn(null) === "—", formatUsdBn(null), "—");
check("parties line", partiesLine(deal()) === "Acme Re (reinsurer) · Cedant Life (cedant)", partiesLine(deal()), "Acme Re (reinsurer) · Cedant Life (cedant)");
check("latest activity takes milestones into account",
  lastActivity(deal({ status: "pending", closed: undefined, milestones: [{ date: "2026-05-01", event: "vote" }] })) === "2026-05-01", "—", "2026-05-01");
{
  const pend = deal({ status: "pending", closed: undefined, verified: "2026-08-01" });
  const fresh = statusLine(pend, "2026-08-20"), old = statusLine(pend, "2026-10-20");
  check(`pending re-check flag after ${RECHECK_DAYS} days`, !fresh.recheck && old.recheck, [fresh.recheck, old.recheck], [false, true]);
  check("closed status names its date", statusLine(deal()).text === "Closed 1 Mar 2026", statusLine(deal()).text, "Closed 1 Mar 2026");
}

console.log("\nview");
{
  const data = { updated: "2026-10-01", deals: [
    deal({ id: "a", announced: "2026-01-10", closed: "2026-02-01", size: { usd_bn: 10, basis: "reserves", text: "x" } }),
    deal({ id: "b", type: "m_and_a", status: "pending", closed: undefined, announced: "2026-06-01", size: { usd_bn: 22, basis: "equity value", text: "x" },
      parties: [{ name: "Big Holdco", role: "acquirer" }] }),
    deal({ id: "c", type: "sidecar", announced: "2026-03-01", closed: "2026-09-01", size: { usd_bn: 1, basis: "liabilities", text: "x" } }),
    deal({ id: "d", status: "pending", closed: undefined, announced: "2026-04-01", size: null }),
    deal({ id: "e", sources: [] }),
  ] };
  const all = buildDealsView(data);
  check("rejected entry stays off the page", all.total === 4 && all.rejected.length === 1 && !all.deals.some(d => d.id === "e"),
    [all.total, all.rejected.length], [4, 1]);
  check("recent sort uses latest activity", eq(all.deals.map(d => d.id), ["c", "b", "d", "a"]), all.deals.map(d => d.id), ["c", "b", "d", "a"]);
  check("announced sort", eq(buildDealsView(data, { sort: "announced" }).deals.map(d => d.id), ["b", "d", "c", "a"]), "—", ["b", "d", "c", "a"]);
  check("size sort puts undisclosed last", eq(buildDealsView(data, { sort: "size" }).deals.map(d => d.id), ["b", "a", "c", "d"]),
    buildDealsView(data, { sort: "size" }).deals.map(d => d.id), ["b", "a", "c", "d"]);
  check("type filter", eq(buildDealsView(data, { type: "sidecar" }).deals.map(d => d.id), ["c"]), "—", ["c"]);
  check("status filter", eq(buildDealsView(data, { status: "pending" }).deals.map(d => d.id).sort(), ["b", "d"]), "—", ["b", "d"]);
  check("search matches party names, any word order", eq(buildDealsView(data, { query: "holdco big" }).deals.map(d => d.id), ["b"]), "—", ["b"]);
  check("search with no match", buildDealsView(data, { query: "zzz" }).deals.length === 0, "—", 0);
  const s = dealStats(vetDeals(data).deals);
  check("stats: liabilities reinsured sums closed reserves/liabilities only", eq(s, { total: 4, closed: 2, pending: 2, liabilitiesUsdBn: 11, liabilitiesDeals: 2 }),
    s, { total: 4, closed: 2, pending: 2, liabilitiesUsdBn: 11, liabilitiesDeals: 2 });
  check("counts by type", all.typeCounts.block_reinsurance === 2 && all.typeCounts.m_and_a === 1, all.typeCounts, "2 block, 1 M&A");
  check("recentDeals caps the list", recentDeals(data, 2).length === 2 && recentDeals(data, 2)[0].id === "c", "—", "c first, 2 items");
  check("no data ⇒ empty view", buildDealsView(undefined).deals.length === 0 && buildDealsView(undefined).stats.total === 0, "—", 0);
}

console.log("\ndata/deals.json");
{
  const file = JSON.parse(readFileSync(new URL("../data/deals.json", import.meta.url), "utf8"));
  const { deals, rejected } = vetDeals(file);
  for (const r of rejected) console.log(`         ${r.id}: ${r.problems.join("; ")}`);
  check("every deal in the file passes vetting", rejected.length === 0, rejected.map(r => r.id), []);
  check("file has deals", deals.length > 0, deals.length, ">0");
  check("every deal has a primary source", deals.every(d => d.sources.some(s => s.kind === "primary")), "—", "all");
  check("updated is a date no earlier than any verified check",
    isIsoDate(file.updated) && deals.every(d => d.verified <= file.updated), file.updated, "≥ every verified");
  const noUsd = deals.filter(d => d.size && d.size.usd_bn == null && /\$/.test(d.size.text));
  check("a size quoted in $ carries its usd_bn figure", noUsd.length === 0, noUsd.map(d => d.id), []);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
