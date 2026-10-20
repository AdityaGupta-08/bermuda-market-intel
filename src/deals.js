/* Deals tracker: vetting rules, filters and the figures the page shows,
   built from data/deals.json (hand-curated, not written by the pipeline).
   Pure, so it is testable without a browser (scripts/test_deals.mjs);
   rendering lives in Deals.jsx.

   The vetting rules here run twice: in CI against the real file, and in the
   browser, where an entry that breaks them is left off the page rather than
   shown without its sources. */

export const TYPE_TEXT = {
  block_reinsurance: "Block reinsurance",
  sidecar: "Sidecar / flow",
  m_and_a: "M&A",
  capital: "Capital raise",
  restructuring: "Restructuring",
};
export const STATUS_TEXT = { closed: "Closed", pending: "Pending", terminated: "Terminated" };
// What a size figure measures. Only reserves and liabilities are summed
// (as "liabilities reinsured"); the rest are not comparable with each other.
export const BASIS_TEXT = {
  reserves: "reserves",
  liabilities: "liabilities",
  "account value": "account value",
  "purchase price": "purchase price",
  "equity value": "equity value",
  capital: "capital",
  assets: "assets",
};
export const SOURCE_KIND_TEXT = { primary: "Primary", secondary: "Coverage" };
const LIABILITY_BASES = new Set(["reserves", "liabilities"]);

// A pending deal not re-checked for this long gets a "re-check" flag.
export const RECHECK_DAYS = 45;

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const ID_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;
// Redirect and archive wrappers hide the real publisher, so they don't count as a reference.
const WRAPPER_HOSTS = ["news.google.com", "archive.ph", "archive.today", "web.archive.org"];

const isNum = v => typeof v === "number" && Number.isFinite(v);
const isText = v => typeof v === "string" && v.trim().length > 0;

/** True for a real calendar date written YYYY-MM-DD. */
export function isIsoDate(s) {
  if (typeof s !== "string" || !DATE_RE.test(s)) return false;
  const d = new Date(`${s}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
}

const daysBetween = (a, b) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000);

function urlProblem(url) {
  let u;
  try { u = new URL(url); } catch { return "is not a valid URL"; }
  if (u.protocol !== "https:") return "must use https";
  if (WRAPPER_HOSTS.some(h => u.hostname === h || u.hostname.endsWith(`.${h}`))) return `links via ${u.hostname}, not the publisher`;
  return null;
}

/** Every rule a deal breaks, as readable strings; empty means it is vetted. */
export function validateDeal(d) {
  const p = [];
  if (!d || typeof d !== "object") return ["is not an object"];
  if (!isText(d.id) || !ID_RE.test(d.id)) p.push("id must be lower-case words joined by hyphens");
  if (!isText(d.title)) p.push("missing title");
  if (!isText(d.summary)) p.push("missing summary");
  if (!TYPE_TEXT[d.type]) p.push(`unknown type "${d.type}"`);
  if (!STATUS_TEXT[d.status]) p.push(`unknown status "${d.status}"`);
  if (!isText(d.region)) p.push("missing region");

  if (!isIsoDate(d.announced)) p.push("announced must be a YYYY-MM-DD date");
  if (!isIsoDate(d.verified)) p.push("verified must be a YYYY-MM-DD date");
  if (d.status === "closed" && !isIsoDate(d.closed)) p.push("closed deal needs a closed date");
  if (d.status !== "closed" && d.closed != null) p.push("only a closed deal has a closed date");
  if (d.status === "terminated" && !isIsoDate(d.terminated)) p.push("terminated deal needs a terminated date");
  // Nothing on the card may post-date the check that vetted it.
  if (isIsoDate(d.verified))
    for (const k of ["announced", "closed", "terminated"])
      if (isIsoDate(d[k]) && d[k] > d.verified) p.push(`${k} date is after the verified date`);

  if (!Array.isArray(d.parties) || d.parties.length === 0) p.push("needs at least one party");
  else d.parties.forEach((x, i) => {
    if (!isText(x?.name) || !isText(x?.role)) p.push(`party ${i + 1} needs a name and a role`);
  });

  if (d.size != null) {
    if (!isText(d.size.text)) p.push("size needs its text as the source states it");
    if (!BASIS_TEXT[d.size.basis]) p.push(`unknown size basis "${d.size.basis}"`);
    if (d.size.usd_bn != null && !(isNum(d.size.usd_bn) && d.size.usd_bn > 0)) p.push("size.usd_bn must be a positive number");
  }

  for (const [i, m] of (d.milestones || []).entries()) {
    if (!isIsoDate(m?.date) || !isText(m?.event)) p.push(`milestone ${i + 1} needs a date and an event`);
    else if (isIsoDate(d.verified) && m.date > d.verified) p.push(`milestone ${i + 1} is after the verified date`);
  }

  const sources = Array.isArray(d.sources) ? d.sources : [];
  if (!sources.length) p.push("needs at least one source");
  const seen = new Set();
  sources.forEach((s, i) => {
    const n = `source ${i + 1}`;
    if (!isText(s?.label) || !isText(s?.publisher)) p.push(`${n} needs a label and a publisher`);
    if (!SOURCE_KIND_TEXT[s?.kind]) p.push(`${n} kind must be primary or secondary`);
    if (s?.date != null && !isIsoDate(s.date)) p.push(`${n} date must be YYYY-MM-DD`);
    const bad = isText(s?.url) ? urlProblem(s.url) : "has no URL";
    if (bad) p.push(`${n} ${bad}`);
    if (isText(s?.url)) { if (seen.has(s.url)) p.push(`${n} repeats a URL`); seen.add(s.url); }
  });
  if (sources.length && !sources.some(s => s?.kind === "primary")) p.push("needs a primary source (company release, filing or regulator)");
  return p;
}

/** Splits the file into vetted deals and rejected entries (with reasons).
    Duplicate ids reject every copy, so neither silently wins. */
export function vetDeals(data) {
  const all = Array.isArray(data?.deals) ? data.deals : [];
  const counts = {};
  for (const d of all) if (d?.id) counts[d.id] = (counts[d.id] || 0) + 1;
  const deals = [], rejected = [];
  all.forEach((d, i) => {
    const problems = validateDeal(d);
    if (d?.id && counts[d.id] > 1) problems.push("duplicate id");
    if (problems.length) rejected.push({ id: d?.id || `entry ${i + 1}`, problems });
    else deals.push(d);
  });
  return { deals, rejected };
}

/** Latest dated event on a deal: what "recent" sorts by. */
export function lastActivity(d) {
  const dates = [d.announced, d.closed, d.terminated, ...(d.milestones || []).map(m => m.date)].filter(isIsoDate);
  return dates.sort().at(-1) || null;
}

// ── Formatting ──

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "2026-07-30" -> "30 Jul 2026". */
export function formatDate(s) {
  if (!isIsoDate(s)) return "—";
  const [y, m, d] = s.split("-");
  return `${Number(d)} ${MONTHS[Number(m) - 1]} ${y}`;
}

/** $bn figure as people write it: "$32bn", "$6.3bn", "$625m". */
export function formatUsdBn(v) {
  if (!isNum(v)) return "—";
  if (v < 1) return `$${Math.round(v * 1000)}m`;
  return `$${v >= 10 ? Math.round(v) : Math.round(v * 10) / 10}bn`;
}

/** "Talcott Financial Group (reinsurer) · Lincoln Financial (cedant)". */
export const partiesLine = d => d.parties.map(x => `${x.name} (${x.role})`).join(" · ");

/** Status words for the card. Pending deals say how long ago they were checked,
    so a stale "pending" can't pass for current. */
export function statusLine(d, today) {
  if (d.status === "closed") return { text: `Closed ${formatDate(d.closed)}`, tone: "closed" };
  if (d.status === "terminated") return { text: `Terminated ${formatDate(d.terminated)}`, tone: "terminated" };
  const age = today && isIsoDate(today) ? daysBetween(d.verified, today) : null;
  return {
    text: "Pending",
    tone: "pending",
    checked: `status checked ${formatDate(d.verified)}`,
    recheck: age != null && age > RECHECK_DAYS,
  };
}

// ── View ──

export const SORTS = { recent: "Latest activity", announced: "Announced date", size: "Largest (USD figures)" };

const haystack = d => [
  d.title, d.summary, d.region, d.note, TYPE_TEXT[d.type], STATUS_TEXT[d.status],
  ...d.parties.map(x => x.name), ...d.sources.map(s => s.publisher),
].filter(Boolean).join(" ").toLowerCase();

const bySort = {
  recent: (a, b) => (lastActivity(b) || "").localeCompare(lastActivity(a) || "") || b.announced.localeCompare(a.announced),
  announced: (a, b) => b.announced.localeCompare(a.announced),
  // Deals without a USD figure go last, newest first among themselves.
  size: (a, b) => (b.size?.usd_bn ?? -1) - (a.size?.usd_bn ?? -1) || b.announced.localeCompare(a.announced),
};

/** Headline figures over a set of vetted deals. */
export function dealStats(deals) {
  const closed = deals.filter(d => d.status === "closed");
  const ceded = closed.filter(d => LIABILITY_BASES.has(d.size?.basis) && isNum(d.size?.usd_bn));
  return {
    total: deals.length,
    closed: closed.length,
    pending: deals.filter(d => d.status === "pending").length,
    liabilitiesUsdBn: Math.round(ceded.reduce((s, d) => s + d.size.usd_bn, 0) * 10) / 10,
    liabilitiesDeals: ceded.length,
  };
}

/** Everything the page renders. Filters: type, status ("all" or a key) and a
    free-text query over titles, parties, publishers and summaries. */
export function buildDealsView(data, { type = "all", status = "all", query = "", sort = "recent", today = null } = {}) {
  const { deals, rejected } = vetDeals(data);
  const q = query.trim().toLowerCase();
  const shown = deals
    .filter(d => type === "all" || d.type === type)
    .filter(d => status === "all" || d.status === status)
    .filter(d => !q || q.split(/\s+/).every(w => haystack(d).includes(w)))
    .sort(bySort[sort] || bySort.recent);
  const countBy = key => deals.reduce((m, d) => ({ ...m, [d[key]]: (m[d[key]] || 0) + 1 }), {});
  return {
    updated: data?.updated || null,
    scope: data?.scope || null,
    vetting: Array.isArray(data?.vetting) ? data.vetting : [],
    excluded: Array.isArray(data?.excluded) ? data.excluded : [],
    stats: dealStats(deals),
    typeCounts: countBy("type"),
    statusCounts: countBy("status"),
    deals: shown.map(d => ({ ...d, statusInfo: statusLine(d, today), activity: lastActivity(d) })),
    total: deals.length,
    rejected,
  };
}

/** Newest few deals by latest activity, for the Overview card. */
export function recentDeals(data, n = 5, today = null) {
  return buildDealsView(data, { sort: "recent", today }).deals.slice(0, n);
}
