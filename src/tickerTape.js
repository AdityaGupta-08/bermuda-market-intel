/* Ticker tape: the groups and items the scrolling strip shows, built from the
   same JSON the pages read. Pure, so it is testable without a browser
   (scripts/test_ticker_tape.mjs); rendering lives in TickerTape.jsx. */

export const TAPE_TENORS = ["2Y", "10Y", "30Y"];

// Country colours match the rate pages (and the Overview curve chart).
export const TAPE_GROUPS = [
  { key: "us",     code: "US", label: "United States", color: "#3b82f6", page: "ust",    curve: "ust",    curveLabel: "UST" },
  { key: "uk",     code: "UK", label: "United Kingdom", color: "#22c55e", page: "gilt",   curve: "gilt",   curveLabel: "Gilt" },
  { key: "eu",     code: "EU", label: "Euro area",      color: "#f59e0b", page: "eiopa",  curve: "eiopa",  curveLabel: "EUR" },
  { key: "jp",     code: "JP", label: "Japan",          color: "#ef4444", page: "jgb",    curve: "jgb",    curveLabel: "JGB" },
  { key: "in",     code: "IN", label: "India",          color: "#ec4899", page: "india",  curve: "india",  curveLabel: "IGB" },
  { key: "global", code: "GL", label: "Global",         color: "#a3a3a3", page: "commodities" },
];

// Commodities sit with the market that prices them: WTI (NYMEX, Cushing) with
// the US, Brent (ICE Futures Europe, North Sea) with the UK, USD/INR with
// India; gold is quoted globally.
const COMMODITY_HOME = { wti: "us", brent: "uk", usdinr: "in", gold: "global" };
const COMMODITY_LABEL = { wti: "WTI", brent: "Brent", usdinr: "USD/INR", gold: "Gold" };

const isNum = v => typeof v === "number" && Number.isFinite(v);

function curveItems(curve, label) {
  if (!curve?.tenors) return [];
  const flagOf = t =>
    curve.held?.[t] ? "held" : curve.interpolated?.includes(t) ? "interpolated" : curve.cached?.includes(t) ? "cached" : null;
  return TAPE_TENORS.flatMap(t => {
    const i = curve.tenors.indexOf(t);
    const v = i >= 0 ? curve.yields?.[i] : null;
    if (!isNum(v)) return [];
    const p = curve.prior_yields?.[i];
    return [{
      id: `${label}-${t}`, label: `${label} ${t}`, kind: "yield", value: v,
      change: isNum(p) ? Math.round((v - p) * 1000) / 10 : null, // bp, 1dp
      flag: flagOf(t),
    }];
  });
}

function commodityItem(key, c) {
  if (!c || !isNum(c.spot)) return null;
  const fx = key === "usdinr";
  const p = c.prior_1d;
  return {
    id: key, label: COMMODITY_LABEL[key], kind: fx ? "fx" : "usd", value: c.spot,
    change: isNum(p) ? Math.round((c.spot - p) * (fx ? 1e4 : 100)) / (fx ? 1e4 : 100) : null,
    changePct: isNum(p) && p ? Math.round(((c.spot - p) / p) * 1e4) / 100 : null,
    flag: c.spot_source === "cache" ? "cached" : null,
  };
}

/** Groups (in TAPE_GROUPS order) with at least one item; empty groups are dropped. */
export function buildTickerGroups(data = {}) {
  const items = Object.fromEntries(TAPE_GROUPS.map(g => [g.key, g.curve ? curveItems(data[g.curve], g.curveLabel) : []]));
  const sofr = data.sofr?.rates?.SOFR;
  if (isNum(sofr?.rate)) {
    items.us.push({
      id: "sofr", label: "SOFR", kind: "yield", value: sofr.rate,
      change: isNum(sofr.prior) ? Math.round((sofr.rate - sofr.prior) * 1000) / 10 : null, flag: null,
    });
  }
  for (const [key, home] of Object.entries(COMMODITY_HOME)) {
    const it = commodityItem(key, data.commodities?.[key]);
    if (it) items[home].push(it);
  }
  return TAPE_GROUPS.filter(g => items[g.key].length).map(g => ({ ...g, items: items[g.key] }));
}

/** Display strings for one item: value, change magnitude, and direction
    (-1/0/1). The tape shows direction with an arrow, so the change is unsigned. */
export function formatTapeItem(it) {
  const money = v => v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const value = it.kind === "yield" ? `${it.value.toFixed(2)}%` : it.kind === "fx" ? it.value.toFixed(2) : `$${money(it.value)}`;
  if (it.change == null) return { value, change: null, dir: 0 };
  const dir = it.change > 0 ? 1 : it.change < 0 ? -1 : 0;
  const mag = Math.abs(it.change);
  const change = it.kind === "yield" ? `${mag.toFixed(1)}bp`
    : it.kind === "fx" ? mag.toFixed(2)
    : `${money(mag)}${it.changePct != null ? ` (${Math.abs(it.changePct).toFixed(2)}%)` : ""}`;
  return { value, change, dir };
}
