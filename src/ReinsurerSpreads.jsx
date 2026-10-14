import { useMemo, useState } from "react";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import {
  Building2, AlertTriangle, Loader, ExternalLink, Clock, Info, Table2, BarChart3,
} from "lucide-react";
import {
  QUARTERS_SHOWN, buildReinsurerView, formatValue, formatAxisValue, formatChange, lineScale, quarterLabel, tableRows,
} from "./reinsurerSpreads.js";

/* ═══════════════════════════════════════════════════════════════════
   PE-BACKED LIFE REINSURERS
   12-quarter trends of the spread and operating-earnings figures that the
   PE-backed life/annuity reinsurers publish in SEC filings. One chart per
   metric (never two scales on one chart); every figure links to its filing.
   All data shaping lives in ./reinsurerSpreads.js.
   ═══════════════════════════════════════════════════════════════════ */

// One hue for every chart: identity comes from the card the chart sits in,
// not from colour. Checked against the card surface (dark mode band, contrast).
const HUE = "#2b9fd9";
const SURFACE = "#0d0f14";
const INK = { primary: "#f1f5f9", secondary: "#94a3b8", muted: "#64748b", faint: "#475569" };
const MONO = "'JetBrains Mono', monospace";
const LINK = { color: "#60a5fa", textDecoration: "none" };
const ARROW = { 1: "▲", [-1]: "▼", 0: "■" };

const ExtLink = ({ href, children }) => (
  <a href={href} target="_blank" rel="noopener noreferrer" style={{ ...LINK, display: "inline-flex", alignItems: "center", gap: 3 }}>
    {children} <ExternalLink size={11} />
  </a>
);

const PointTooltip = ({ active, payload, unit }) => {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div style={{ background: "#1e2028", border: "1px solid #334155", borderRadius: 8, padding: "10px 14px", fontSize: 12, maxWidth: 260 }}>
      <div style={{ color: INK.primary, fontWeight: 700, marginBottom: 4 }}>{p.label}</div>
      {p.value == null ? <div style={{ color: INK.muted }}>No figure for this quarter</div> : <>
        <div style={{ color: INK.primary, fontFamily: MONO, fontSize: 14, fontWeight: 600 }}>{formatValue(p.value, unit)}</div>
        {p.revisedFrom != null && <div style={{ color: INK.secondary, marginTop: 3 }}>Restated by a later filing; first reported as {formatValue(p.revisedFrom, unit)}</div>}
        {p.filed && <div style={{ color: INK.muted, marginTop: 3 }}>{p.form} filed {p.filed}</div>}
      </>}
    </div>
  );
};

const axisTick = { fill: INK.muted, fontSize: 10 };

const MetricChart = ({ m }) => {
  const common = {
    data: m.series, margin: { top: 10, right: 16, left: 0, bottom: 0 },
  };
  const x = <XAxis dataKey="label" tick={axisTick} tickLine={false} axisLine={{ stroke: "#1e2028" }} interval="preserveStartEnd" minTickGap={6} />;
  const grid = <CartesianGrid stroke="#1a1d23" vertical={false} />;
  const scale = m.unit === "pct" ? lineScale(m.series.map(s => s.value)) : null;
  // filterNull off: hovering an undisclosed quarter says so instead of showing nothing.
  const tip = cursor => <Tooltip cursor={cursor} filterNull={false} content={<PointTooltip unit={m.unit} />} />;
  return (
    <ResponsiveContainer width="100%" height={190}>
      {m.unit === "pct" ? (
        <LineChart {...common}>
          {grid}{x}
          <YAxis tick={axisTick} tickLine={false} axisLine={false} width={50}
            domain={scale.domain} ticks={scale.ticks} interval={0} tickFormatter={v => formatAxisValue(v, m.unit)} />
          {tip({ stroke: INK.faint, strokeDasharray: "3 3" })}
          <Line dataKey="value" name={m.label} stroke={HUE} strokeWidth={2} connectNulls={false} isAnimationActive={false}
            dot={{ r: 4, fill: HUE, stroke: SURFACE, strokeWidth: 2 }} activeDot={{ r: 6, fill: HUE, stroke: SURFACE, strokeWidth: 2 }} />
        </LineChart>
      ) : (
        <BarChart {...common} barCategoryGap="24%">
          {grid}{x}
          <YAxis tick={axisTick} tickLine={false} axisLine={false} width={58}
            domain={[d => Math.min(0, d), "auto"]} tickFormatter={v => formatAxisValue(v, m.unit)} />
          {tip({ fill: "#ffffff08" })}
          <Bar dataKey="value" name={m.label} fill={HUE} radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
        </BarChart>
      )}
    </ResponsiveContainer>
  );
};

const Change = ({ ch, unit, label }) => {
  const f = formatChange(ch, unit);
  return (
    <span style={{ whiteSpace: "nowrap" }}>
      <span style={{ color: INK.muted }}>{label} </span>
      {f ? <span style={{ color: INK.secondary, fontFamily: MONO }}>{ARROW[f.dir]} {f.text}</span>
        : <span style={{ color: INK.faint }}>n/a</span>}
    </span>
  );
};

const MetricPanel = ({ m, view }) => (
  <div style={{ minWidth: 0, border: "1px solid #1a1d23", borderRadius: 10, padding: "14px 14px 8px" }}>
    <div style={{ fontSize: 11, color: INK.secondary, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600 }}>{m.label}</div>
    {m.latest ? <>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, margin: "6px 0 4px" }}>
        <span style={{ fontSize: 24, fontWeight: 700, color: INK.primary, fontFamily: MONO }}>{formatValue(m.latest.value, m.unit)}</span>
        <span style={{ fontSize: 12, color: INK.muted }}>{quarterLabel(m.latest.quarter)}</span>
      </div>
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", fontSize: 12, marginBottom: 6 }}>
        <Change ch={m.qoq} unit={m.unit} label="QoQ" />
        <Change ch={m.yoy} unit={m.unit} label="YoY" />
      </div>
    </> : <div style={{ fontSize: 13, color: INK.muted, margin: "8px 0" }}>No figures read yet</div>}
    {view === "chart" && m.count > 0 && <MetricChart m={m} />}
    {view === "chart" && m.restated.length > 0 && (
      <div style={{ fontSize: 11, color: INK.muted, padding: "2px 4px 4px" }}>
        {m.restated.length === 1 ? `${quarterLabel(m.restated[0])} was` : `${m.restated.map(quarterLabel).join(", ")} were`} restated by a later filing; hover for the original figure.
      </div>
    )}
  </div>
);

const th = { textAlign: "right", padding: "7px 10px", color: INK.secondary, fontWeight: 600, fontSize: 11, borderBottom: "1px solid #1e2028", whiteSpace: "nowrap" };
const td = { textAlign: "right", padding: "7px 10px", color: INK.primary, fontFamily: MONO, borderBottom: "1px solid #151820", whiteSpace: "nowrap" };

const CompanyTable = ({ c }) => {
  const rows = tableRows(c);
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead><tr>
          <th style={{ ...th, textAlign: "left" }}>Quarter</th>
          {c.metrics.map(m => <th key={m.key} style={th}>{m.label}</th>)}
          <th style={{ ...th, textAlign: "left" }}>Source filing</th>
        </tr></thead>
        <tbody>{rows.map(r => (
          <tr key={r.quarter}>
            <td style={{ ...td, textAlign: "left", color: INK.secondary }}>{r.label}</td>
            {r.values.map((v, i) => (
              <td key={i} style={td} title={v.revisedFrom ? `First reported as ${v.revisedFrom}` : undefined}>
                {v.text}{v.revisedFrom && <span style={{ color: INK.muted }}> (was {v.revisedFrom})</span>}
              </td>
            ))}
            <td style={{ ...td, textAlign: "left", fontFamily: "inherit" }}>
              {r.url ? <ExtLink href={r.url}>{r.form} {r.filed}</ExtLink> : <span style={{ color: INK.faint }}>—</span>}
            </td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
};

const ToggleButton = ({ active, onClick, icon: Icon, children }) => (
  <button type="button" onClick={onClick} aria-pressed={active}
    style={{ display: "inline-flex", alignItems: "center", gap: 5, background: active ? "#1e2028" : "transparent", border: "1px solid #2a2d35",
      borderRadius: 6, padding: "4px 10px", fontSize: 12, color: active ? INK.primary : INK.secondary, cursor: "pointer" }}>
    <Icon size={13} />{children}
  </button>
);

const CompanyCard = ({ c }) => {
  const [view, setView] = useState("chart");
  return (
    <section aria-label={c.name} style={{ background: SURFACE, border: "1px solid #1e2028", borderRadius: 12, padding: "18px 20px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
          <h3 style={{ margin: 0, fontSize: 17, fontWeight: 700, color: INK.primary }}>{c.name}</h3>
          <span style={{ fontSize: 12, color: INK.secondary }}>Owner: {c.owner}</span>
        </div>
        {c.hasData && (
          <div style={{ display: "flex", gap: 6 }} role="group" aria-label={`${c.name} view`}>
            <ToggleButton active={view === "chart"} onClick={() => setView("chart")} icon={BarChart3}>Chart</ToggleButton>
            <ToggleButton active={view === "table"} onClick={() => setView("table")} icon={Table2}>Table</ToggleButton>
          </div>
        )}
      </div>

      {c.message && (
        <div style={{ display: "flex", gap: 8, alignItems: "flex-start", background: "#14120c", border: "1px solid #fbbf2433", borderRadius: 8,
          padding: "9px 12px", fontSize: 12, color: INK.secondary, marginBottom: 12, lineHeight: 1.5 }}>
          <AlertTriangle size={14} style={{ color: c.status === "error" ? "#f87171" : "#fbbf24", flexShrink: 0, marginTop: 1 }} />
          <span><strong style={{ color: INK.primary }}>{c.status === "error" ? "Fetch failed" : c.stale ? "Stale" : "Awaiting data"}:</strong> {c.message}</span>
        </div>
      )}

      {c.hasData && (view === "chart" ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))", gap: 12 }}>
          {c.metrics.map(m => <MetricPanel key={m.key} m={m} view={view} />)}
        </div>
      ) : <CompanyTable c={c} />)}

      <div style={{ marginTop: 12, fontSize: 12, color: INK.secondary, lineHeight: 1.6 }}>
        <div>{c.definition}</div>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 4, color: INK.muted }}>
          <span>Source: {c.source}</span>
          {c.latestFiling?.url && <ExtLink href={c.latestFiling.url}>Latest filing ({c.latestFiling.form}, {c.latestFiling.filed})</ExtLink>}
          {c.edgarUrl && <ExtLink href={c.edgarUrl}>All filings on EDGAR</ExtLink>}
        </div>
      </div>
    </section>
  );
};

const NotCovered = ({ groups }) => !groups.length ? null : (
  <section aria-label="Not covered" style={{ background: SURFACE, border: "1px solid #1e2028", borderRadius: 12, padding: "16px 20px" }}>
    <h3 style={{ margin: "0 0 4px", fontSize: 15, fontWeight: 700, color: INK.primary }}>Not covered</h3>
    <div style={{ fontSize: 12, color: INK.muted, marginBottom: 6 }}>PE-backed or affiliated life reinsurers that do not publish these figures in SEC filings.</div>
    {groups.map(g => (
      <div key={g.names.join()} style={{ fontSize: 12, lineHeight: 1.6, padding: "8px 0", borderTop: "1px solid #151820" }}>
        <span style={{ color: INK.primary, fontWeight: 600 }}>{g.names.join(", ")}</span>
        {g.detail && <div style={{ color: INK.secondary, maxWidth: 900 }}>{g.detail}</div>}
      </div>
    ))}
  </section>
);

// A missing file is the normal state before the first SEC run, so the load
// error itself is not shown here (the Overview error list still names it).
export default function ReinsurerSpreadsSection({ data, loading }) {
  const view = useMemo(() => buildReinsurerView(data), [data]);
  const updated = view.updated ? new Date(view.updated).toISOString().slice(0, 10) : null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ background: SURFACE, border: "1px solid #1e2028", borderRadius: 12, padding: "18px 22px" }}>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: INK.primary, display: "flex", alignItems: "center", gap: 9 }}>
          <Building2 size={20} /> PE-Backed Life Reinsurers
        </h2>
        <div style={{ fontSize: 13, color: INK.secondary, marginTop: 6, lineHeight: 1.55, maxWidth: 860 }}>
          Spread and operating earnings for the private-equity-backed life and annuity reinsurers that disclose them in SEC filings,
          last {QUARTERS_SHOWN} quarters. Each figure links to the filing it was read from.
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: INK.secondary, marginTop: 8, flexWrap: "wrap" }}>
          <Clock size={13} /><span>Updated {updated || "—"}</span>
          <span style={{ color: INK.faint }}>|</span>
          <ExtLink href="https://www.sec.gov/edgar/search/">SEC EDGAR</ExtLink>
        </div>
        {view.note && (
          <div style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 12, padding: "9px 12px", background: "#0f1520",
            border: "1px solid #1e3a5f", borderRadius: 8, fontSize: 12, color: INK.secondary, lineHeight: 1.5 }}>
            <Info size={14} style={{ color: "#60a5fa", flexShrink: 0, marginTop: 1 }} />
            <span>{view.note}</span>
          </div>
        )}
      </div>

      {loading && !data && (
        <div style={{ padding: 24, color: INK.secondary, fontSize: 13 }}>
          <Loader size={16} style={{ verticalAlign: "middle", marginRight: 8, animation: "spin 1s linear infinite" }} />Loading SEC disclosures…
        </div>
      )}
      {!loading && !data && (
        <div style={{ background: SURFACE, border: "1px solid #1e2028", borderRadius: 12, padding: "16px 20px", fontSize: 13, color: INK.secondary, lineHeight: 1.6 }}>
          <AlertTriangle size={14} style={{ verticalAlign: "middle", marginRight: 6, color: "#fbbf24" }} />
          No SEC disclosure data yet. The scheduled data refresh reads the filings and writes it; it appears after the next run.
        </div>
      )}

      {view.companies.map(c => <CompanyCard key={c.key} c={c} />)}
      <NotCovered groups={view.notCovered} />
    </div>
  );
}
