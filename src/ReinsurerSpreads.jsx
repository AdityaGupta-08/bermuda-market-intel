import { useMemo, useState } from "react";
import {
  BarChart, Bar, Cell, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import {
  Building2, AlertTriangle, Loader, ExternalLink, Clock, Info, Table2, BarChart3,
  CircleCheck, CircleMinus, CircleAlert, MessageSquareText, Eye, ChevronDown, ChevronUp,
} from "lucide-react";
import {
  QUARTERS_SHOWN, SOURCE_TEXT, TONE_TEXT, buildReinsurerView, defaultReasonQuarter, formatValue, formatAxisValue,
  formatChange, lineScale, quarterLabel, tableRows,
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
        {p.filed && p.source === "sec" && <div style={{ color: INK.muted, marginTop: 3 }}>{p.form} filed {p.filed}</div>}
        {p.filed && p.source !== "sec" && (
          <div style={{ color: INK.secondary, marginTop: 3 }}>From the {SOURCE_TEXT[p.source] || "company document"}, not an SEC filing (read {p.filed}); replaced once the filing is read</div>
        )}
      </>}
    </div>
  );
};

const axisTick = { fill: INK.muted, fontSize: 10 };

// SEC figures: solid dots. Call/release figures: hollow, so the source reads
// without relying on colour.
const FallbackAwareDot = ({ cx, cy, payload, index }) => {
  if (cx == null || cy == null || payload?.value == null) return <g key={index} />;
  const fallback = payload.source && payload.source !== "sec";
  return <circle key={index} cx={cx} cy={cy} r={4} strokeWidth={2}
    fill={fallback ? SURFACE : HUE} stroke={fallback ? HUE : SURFACE} />;
};

const MetricChart = ({ m, selected, onSelect }) => {
  const common = {
    data: m.series, margin: { top: 10, right: 16, left: 0, bottom: 0 },
    // Clicking a quarter opens its reasons below the charts.
    onClick: st => { const q = st?.activePayload?.[0]?.payload?.quarter; if (q && onSelect) onSelect(q); },
    style: { cursor: onSelect ? "pointer" : "default" },
  };
  const mark = selected && m.series.some(p => p.quarter === selected)
    ? <ReferenceLine x={quarterLabel(selected)} stroke={INK.secondary} strokeDasharray="3 3" ifOverflow="extendDomain" />
    : null;
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
          {mark}
          <Line dataKey="value" name={m.label} stroke={HUE} strokeWidth={2} connectNulls={false} isAnimationActive={false}
            dot={FallbackAwareDot} activeDot={{ r: 6, fill: HUE, stroke: SURFACE, strokeWidth: 2 }} />
        </LineChart>
      ) : (
        <BarChart {...common} barCategoryGap="24%">
          {grid}{x}
          <YAxis tick={axisTick} tickLine={false} axisLine={false} width={58}
            domain={[d => Math.min(0, d), "auto"]} tickFormatter={v => formatAxisValue(v, m.unit)} />
          {tip({ fill: "#ffffff08" })}
          {mark}
          <Bar dataKey="value" name={m.label} fill={HUE} radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false}>
            {m.series.map(d => (d.source && d.source !== "sec"
              ? <Cell key={d.quarter} fill={HUE} fillOpacity={0.25} stroke={HUE} strokeWidth={1.5} strokeDasharray="4 2" />
              : <Cell key={d.quarter} fill={HUE} />))}
          </Bar>
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

const MetricPanel = ({ m, view, selected, onSelect }) => (
  <div style={{ minWidth: 0, border: "1px solid #1a1d23", borderRadius: 10, padding: "14px 14px 8px" }}>
    <div style={{ fontSize: 11, color: INK.secondary, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600 }}>{m.label}</div>
    {m.latest ? <>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, margin: "6px 0 4px" }}>
        <span style={{ fontSize: 24, fontWeight: 700, color: INK.primary, fontFamily: MONO }}>{formatValue(m.latest.value, m.unit)}</span>
        <span style={{ fontSize: 12, color: INK.muted }}>{quarterLabel(m.latest.quarter)}</span>
        {m.latest.source && m.latest.source !== "sec" && (
          <span style={{ fontSize: 11, color: INK.secondary, border: "1px dashed #475569", borderRadius: 4, padding: "0 5px" }}>
            from {SOURCE_TEXT[m.latest.source] || "company document"}
          </span>
        )}
      </div>
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", fontSize: 12, marginBottom: 6 }}>
        <Change ch={m.qoq} unit={m.unit} label="QoQ" />
        <Change ch={m.yoy} unit={m.unit} label="YoY" />
      </div>
    </> : <div style={{ fontSize: 13, color: INK.muted, margin: "8px 0" }}>No figures read yet</div>}
    {view === "chart" && m.count > 0 && <MetricChart m={m} selected={selected} onSelect={onSelect} />}
    {view === "chart" && m.fallbackQuarters.length > 0 && (
      <div style={{ fontSize: 11, color: INK.muted, padding: "2px 4px 0" }}>
        {m.unit === "pct" ? "Hollow points" : "Outlined bars"} ({m.fallbackQuarters.map(quarterLabel).join(", ")}) come from the
        company&rsquo;s earnings call transcript or results release, not an SEC filing; they&rsquo;re replaced once the filing is read.
      </div>
    )}
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
          <th style={{ ...th, textAlign: "left" }}>Source</th>
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
              {r.url ? <ExtLink href={r.url}>{r.sourceText}</ExtLink> : <span style={{ color: INK.faint }}>—</span>}
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

// Sentiment of a call, as tagged in the review. Status colours always ship
// with an icon and the word, never colour alone.
const TONE = {
  good: { color: "#4ade80", Icon: CircleCheck },
  average: { color: "#fbbf24", Icon: CircleMinus },
  bad: { color: "#f87171", Icon: CircleAlert },
};
const toneOf = label => TONE[(label || "").toLowerCase()] ? (label || "").toLowerCase() : "average";
const fmtScore = v => (v == null ? "" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}`);

const TonePill = ({ meter }) => {
  if (!meter) return null;
  const t = TONE[toneOf(meter.label)];
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, border: `1px solid ${t.color}55`, background: `${t.color}14`,
      borderRadius: 999, padding: "2px 9px", fontSize: 12, color: INK.primary, whiteSpace: "nowrap" }}>
      <t.Icon size={13} style={{ color: t.color }} />{meter.label} <span style={{ fontFamily: MONO, color: INK.secondary }}>{fmtScore(meter.score)}</span>
      {meter.arrow && <span style={{ color: INK.secondary }}>{meter.arrow}</span>}
    </span>
  );
};

const ReasonsPanel = ({ c, selected, onSelect, review }) => {
  const r = c.reasons;
  if (!r) return null;
  const call = r.byQuarter[selected] || null;
  return (
    <div style={{ marginTop: 14, border: "1px solid #1a1d23", borderRadius: 10, padding: "14px 16px" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
        <MessageSquareText size={14} style={{ color: INK.secondary, alignSelf: "center" }} />
        <strong style={{ fontSize: 13, color: INK.primary }}>Why it moved</strong>
        <span style={{ fontSize: 12, color: INK.muted }}>
          Management commentary from each earnings call{r.metric ? ` on ${r.metric}` : ""}, tagged in your earnings call review
          {review?.as_of ? ` (as of ${review.as_of})` : ""}. Pick a quarter, or click one on the charts.
        </span>
      </div>
      <div role="group" aria-label={`${c.name} earnings calls`} style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
        {r.calls.map(x => {
          const t = TONE[toneOf(x.meter?.label)];
          const on = x.quarter === selected;
          return (
            <button key={x.quarter} type="button" onClick={() => onSelect(x.quarter)} aria-pressed={on}
              title={`${x.label}: ${x.meter ? `${x.meter.label} (${fmtScore(x.meter.score)})` : "no meter"}`}
              style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 8px", borderRadius: 6, cursor: "pointer",
                border: `1px solid ${on ? INK.secondary : "#2a2d35"}`, background: on ? "#1e2028" : "transparent",
                color: on ? INK.primary : INK.secondary, fontSize: 11, fontFamily: MONO }}>
              <t.Icon size={11} style={{ color: t.color }} aria-hidden="true" />{x.label}
            </button>
          );
        })}
      </div>
      {call ? (
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 8, fontSize: 12, color: INK.secondary }}>
            <strong style={{ color: INK.primary, fontSize: 13 }}>{call.label} call</strong>
            {call.date && <span>{call.date}</span>}
            <TonePill meter={call.meter} />
            {call.read && <span style={{ color: INK.muted }}>{call.read}</span>}
            {call.sources.map(src => <ExtLink key={src.url} href={src.url}>{src.label}</ExtLink>)}
          </div>
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
            {call.lines.map((l, i) => {
              const t = TONE[l.tone] || TONE.average;
              return (
                <li key={i} style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 12.5, lineHeight: 1.5, color: INK.primary }}>
                  <t.Icon size={14} style={{ color: t.color, flexShrink: 0, marginTop: 2 }} aria-label={TONE_TEXT[l.tone] || "Average"} />
                  <span>
                    {l.theme && <span style={{ fontSize: 11, color: INK.secondary, border: "1px solid #2a2d35", borderRadius: 4, padding: "0 5px", marginRight: 6 }}>{l.theme}</span>}
                    {l.text}
                  </span>
                </li>
              );
            })}
          </ul>
          {call.meter?.note && <div style={{ fontSize: 11.5, color: INK.muted, marginTop: 8 }}>{call.meter.note}</div>}
        </div>
      ) : (
        <div style={{ fontSize: 12, color: INK.muted }}>No call commentary for {quarterLabel(selected)} in the review yet.</div>
      )}
      {r.watch && (
        <div style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 12, paddingTop: 10, borderTop: "1px solid #151820",
          fontSize: 12, color: INK.secondary, lineHeight: 1.5 }}>
          <Eye size={14} style={{ flexShrink: 0, marginTop: 2 }} />
          <span><strong style={{ color: INK.primary }}>Watch on the next call:</strong> {r.watch}</span>
        </div>
      )}
    </div>
  );
};

const CompanyCard = ({ c, review }) => {
  const [view, setView] = useState("chart");
  const [selected, setSelected] = useState(() => defaultReasonQuarter(c));
  return (
    <section aria-label={c.name} style={{ background: SURFACE, border: "1px solid #1e2028", borderRadius: 12, padding: "18px 20px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
          <h3 style={{ margin: 0, fontSize: 17, fontWeight: 700, color: INK.primary }}>{c.name}</h3>
          {c.owner && <span style={{ fontSize: 12, color: INK.secondary }}>Owner: {c.owner}</span>}
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
          <span><strong style={{ color: INK.primary }}>{c.status === "error" ? "Fetch failed" : c.stale && c.usesFallback ? "SEC filings unavailable" : c.stale ? "Stale" : "Awaiting data"}:</strong> {c.message}</span>
        </div>
      )}

      {c.hasData && (view === "chart" ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))", gap: 12 }}>
          {c.metrics.map(m => <MetricPanel key={m.key} m={m} view={view} selected={selected}
            onSelect={c.reasons ? setSelected : undefined} />)}
        </div>
      ) : <CompanyTable c={c} />)}

      <ReasonsPanel c={c} selected={selected} onSelect={setSelected} review={review} />

      <div style={{ marginTop: 12, fontSize: 12, color: INK.secondary, lineHeight: 1.6 }}>
        {c.scope && <div style={{ color: INK.primary }}>{c.scope}</div>}
        {c.definition && <div>{c.definition}</div>}
        {c.fallbackNote && <div style={{ color: INK.muted, marginTop: 2 }}>{c.fallbackNote}</div>}
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 4, color: INK.muted }}>
          {c.source && <span>Source: {c.source}</span>}
          {c.fallbackSource && <span>Fallback when a filing can&rsquo;t be read: {c.fallbackSource}</span>}
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
const ReviewSummary = ({ review }) => {
  const [open, setOpen] = useState(false);
  if (!review) return null;
  const shown = open ? review.summary : review.summary.slice(0, 3);
  return (
    <div style={{ marginTop: 12, padding: "10px 12px", border: "1px solid #1e2028", borderRadius: 8, fontSize: 12, color: INK.secondary, lineHeight: 1.55 }}>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: shown.length ? 6 : 0 }}>
        <MessageSquareText size={14} />
        <strong style={{ color: INK.primary }}>Across the group</strong>
        <span style={{ color: INK.muted }}>from your earnings call review, as of {review.as_of}</span>
        {review.url && <ExtLink href={review.url}>Open the review</ExtLink>}
        {review.mdna_url && <ExtLink href={review.mdna_url}>MD&amp;A review</ExtLink>}
      </div>
      <ul style={{ margin: 0, paddingLeft: 18 }}>{shown.map((b, i) => <li key={i}>{b}</li>)}</ul>
      {review.summary.length > 3 && (
        <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open}
          style={{ marginTop: 6, background: "transparent", border: 0, color: "#60a5fa", cursor: "pointer", fontSize: 12, padding: 0,
            display: "inline-flex", alignItems: "center", gap: 3 }}>
          {open ? <>Show less <ChevronUp size={12} /></> : <>Show all {review.summary.length} <ChevronDown size={12} /></>}
        </button>
      )}
    </div>
  );
};

export default function ReinsurerSpreadsSection({ data, commentary, loading }) {
  const view = useMemo(() => buildReinsurerView(data, commentary), [data, commentary]);
  const updated = view.updated ? new Date(view.updated).toISOString().slice(0, 10) : null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ background: SURFACE, border: "1px solid #1e2028", borderRadius: 12, padding: "18px 22px" }}>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: INK.primary, display: "flex", alignItems: "center", gap: 9 }}>
          <Building2 size={20} /> PE-Backed Life Reinsurers
        </h2>
        <div style={{ fontSize: 13, color: INK.secondary, marginTop: 6, lineHeight: 1.55, maxWidth: 860 }}>
          Spread and operating earnings for the PE- and alternative-manager-backed life and annuity (re)insurers with Bermuda
          reinsurance that disclose them in SEC filings, last {QUARTERS_SHOWN} quarters, with the reasons from each earnings call.
          Each figure links to the filing it was read from.
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
        <ReviewSummary review={view.review} />
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

      {view.companies.map(c => <CompanyCard key={c.key} c={c} review={view.review} />)}
      <NotCovered groups={view.notCovered} />
    </div>
  );
}
