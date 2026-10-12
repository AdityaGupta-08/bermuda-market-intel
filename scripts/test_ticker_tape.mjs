/* Checks for the ticker-tape groups and formatting.
   Run: node scripts/test_ticker_tape.mjs                              */

import { buildTickerGroups, formatTapeItem, TAPE_TENORS } from "../src/tickerTape.js";

let pass = 0, fail = 0;
function check(name, cond, got, want) {
  if (cond) { pass++; console.log(`  ok   ${name}`); }
  else { fail++; console.log(`  FAIL ${name}\n         got  ${JSON.stringify(got)}\n         want ${JSON.stringify(want)}`); }
}

const curve = (yields, prior, extra = {}) => ({
  tenors: ["1Y", "2Y", "5Y", "10Y", "30Y"], yields, prior_yields: prior, ...extra,
});
const data = {
  ust: curve([4.4, 4.79, 5.0, 5.27, 5.6], [4.4, 4.84, 5.0, 5.31, 5.6]),
  jgb: curve([1.6, 1.9, 2.4, 3.08, 4.17], null),
  gilt: curve([4.5, 4.68, 4.9, 5.4, 5.93], [4.5, 4.68, 4.9, 5.37, 5.89], { held: { "2Y": 1 }, interpolated: ["15Y"] }),
  india: curve([6.1, null, 6.9, 7.21, 7.68], [6.1, 6.6, 6.9, 7.21, 7.71]),
  sofr: { rates: { SOFR: { rate: 3.87, prior: 3.88 } } },
  commodities: {
    gold: { spot: 4177.96, prior_1d: 4193.87, spot_source: "TradingEconomics" },
    wti: { spot: 92.67, prior_1d: 91.85, spot_source: "Yahoo CL=F (front month)" },
    brent: { spot: 105.63, prior_1d: null, spot_source: "cache" },
    usdinr: { spot: 95.76, prior_1d: 96.8233, spot_source: "Yahoo INR=X" },
  },
};

console.log("\ngrouping");
const groups = buildTickerGroups(data);
check("groups in country order, empty EUR dropped", groups.map(g => g.code).join(",") === "US,UK,JP,IN,GL",
  groups.map(g => g.code), "US,UK,JP,IN,GL");
const us = groups.find(g => g.key === "us");
check("US: 2Y/10Y/30Y, SOFR, then WTI", us.items.map(i => i.label).join("|") === "UST 2Y|UST 10Y|UST 30Y|SOFR|WTI",
  us.items.map(i => i.label), "UST 2Y|UST 10Y|UST 30Y|SOFR|WTI");
check("UK carries Brent", groups.find(g => g.key === "uk").items.some(i => i.id === "brent"), "—", "brent in UK");
check("India carries USD/INR", groups.find(g => g.key === "in").items.some(i => i.id === "usdinr"), "—", "usdinr in IN");
check("gold sits under Global", groups.find(g => g.key === "global").items.map(i => i.id).join() === "gold", "—", "gold");
check("only the tape tenors appear", us.items.filter(i => i.kind === "yield" && i.id !== "sofr").length === TAPE_TENORS.length,
  us.items.length, TAPE_TENORS.length);
check("missing yield skipped, not shown as 0", !groups.find(g => g.key === "in").items.some(i => i.label === "IGB 2Y"), "—", "no IGB 2Y");

console.log("\nchanges");
const u10 = us.items.find(i => i.label === "UST 10Y");
check("yield change in bp", u10.change === -4, u10.change, -4);
check("no prior curve ⇒ no change", groups.find(g => g.key === "jp").items.every(i => i.change === null), "—", "null");
const wti = us.items.find(i => i.id === "wti");
check("commodity change in $ and %", wti.change === 0.82 && wti.changePct === 0.89, [wti.change, wti.changePct], [0.82, 0.89]);
const inr = groups.find(g => g.key === "in").items.find(i => i.id === "usdinr");
check("FX change to 4dp", inr.change === -1.0633, inr.change, -1.0633);

console.log("\nprovenance flags");
check("held tenor flagged", groups.find(g => g.key === "uk").items.find(i => i.label === "Gilt 2Y").flag === "held", "—", "held");
check("cached spot flagged", groups.find(g => g.key === "uk").items.find(i => i.id === "brent").flag === "cached", "—", "cached");

console.log("\nformatting");
const fy = formatTapeItem(u10);
check("yield value and change", fy.value === "5.27%" && fy.change === "4.0bp" && fy.dir === -1, fy, { value: "5.27%", change: "4.0bp", dir: -1 });
const fg = formatTapeItem(groups.find(g => g.key === "global").items[0]);
check("gold with thousands separator", fg.value === "$4,177.96" && fg.change === "15.91 (0.38%)" && fg.dir === -1, fg, "$4,177.96 / 15.91 (0.38%)");
const fb = formatTapeItem(groups.find(g => g.key === "uk").items.find(i => i.id === "brent"));
check("no prior ⇒ no change string", fb.change === null && fb.dir === 0, fb, { change: null, dir: 0 });

console.log("\nempty input");
check("no data ⇒ no groups", buildTickerGroups({}).length === 0 && buildTickerGroups().length === 0, "—", 0);

console.log(`\n${pass} passed, ${fail} failed\n`);
process.exit(fail ? 1 : 0);
