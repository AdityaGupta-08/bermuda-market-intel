import { useMemo, useState } from "react";
import {
  Handshake, ExternalLink, Clock, Info, Search, CircleCheck, CircleX, AlertTriangle, Loader, ShieldCheck,
  ChevronDown, ChevronUp, ChevronRight, ArrowRight,
} from "lucide-react";
import {
  TYPE_TEXT, STATUS_TEXT, BASIS_TEXT, SOURCE_KIND_TEXT, SORTS, RECHECK_DAYS,
  buildDealsView, recentDeals, formatDate, formatUsdBn,
} from "./deals.js";

/* ═══════════════════════════════════════════════════════════════════
   DEALS TRACKER
   Vetted transactions across the Bermuda life & annuity reinsurers, their
   sponsors and cedants, from the hand-curated data/deals.json. Every card
   lists its references, primary sources first; an entry that fails the
   vetting rules in ./deals.js is held back rather than shown unsourced.
   ═══════════════════════════════════════════════════════════════════ */

const SURFACE = "#0d0f14";
const INK = { primary: "#f1f5f9", secondary: "#94a3b8", muted: "#64748b", faint: "#475569" };
const MONO = "'JetBrains Mono', monospace";
const LINK = { color: "#60a5fa", textDecoration: "none" };

const TYPE_COLOR = {
  block_reinsurance: "#38bdf8", sidecar: "#a78bfa", m_and_a: "#f472b6", capital: "#4ade80", restructuring: "#fbbf24",
};
// Status colours always ship with an icon and the word, never colour alone.
const STATUS_STYLE = {
  closed: { color: "#4ade80", Icon: CircleCheck },
  pending: { color: "#fbbf24", Icon: Clock },
  terminated: { color: "#f87171", Icon: CircleX },
};

const today = () => new Date().toISOString().slice(0, 10);

const Badge = ({ children, color = "#60a5fa" }) => (
  <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em",
    padding: "3px 9px", borderRadius: 4, background: color + "20", color, whiteSpace: "nowrap" }}>{children}</span>
);

const ExtLink = ({ href, children, style }) => (
  <a href={href} target="_blank" rel="noopener noreferrer" style={{ ...LINK, display: "inline-flex", alignItems: "baseline", gap: 4, ...style }}>
    {children}<ExternalLink size={11} style={{ flexShrink: 0, alignSelf: "center" }} />
  </a>
);

const StatusPill = ({ info }) => {
  const s = STATUS_STYLE[info.tone] || STATUS_STYLE.pending;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, border: `1px solid ${s.color}55`, background: `${s.color}14`,
      borderRadius: 999, padding: "2px 9px", fontSize: 12, color: INK.primary, whiteSpace: "nowrap" }}>
      <s.Icon size={13} style={{ color: s.color }} aria-hidden="true" />{info.text}
    </span>
  );
};

// Headline amount when there's no USD figure: the first currency amount in the
// source's own wording ("£5.7bn", "€1.2 billion"), or nothing rather than a stray word.
const AMOUNT_RE = /(?:[A-Z]{1,3})?[£€¥$]\s?\d[\d.,]*\s?(?:bn|tn|m|billion|trillion|million)?/i;

const SizeFigure = ({ size }) => {
  if (!size) return <div style={{ fontSize: 12, color: INK.muted, textAlign: "right", flexShrink: 0, maxWidth: 90 }}>Size not disclosed</div>;
  const headline = size.usd_bn != null ? formatUsdBn(size.usd_bn) : size.text.match(AMOUNT_RE)?.[0].trim();
  if (!headline) return null;
  return (
    <div style={{ textAlign: "right", flexShrink: 0 }}>
      <div style={{ fontSize: 20, fontWeight: 700, color: INK.primary, fontFamily: MONO, lineHeight: 1.1 }}>{headline}</div>
      <div style={{ fontSize: 11, color: INK.muted, marginTop: 2 }}>{BASIS_TEXT[size.basis]}</div>
    </div>
  );
};

// Milestones when the file has them; otherwise the announced/closed dates.
const steps = d => d.milestones?.length ? d.milestones : [
  { date: d.announced, event: "Announced" },
  ...(d.closed ? [{ date: d.closed, event: d.closed < d.announced ? "Effective" : "Closed" }] : []),
  ...(d.terminated ? [{ date: d.terminated, event: "Terminated" }] : []),
];

const Timeline = ({ d }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", fontSize: 12, color: INK.secondary }}>
    {steps(d).map((s, i) => (
      <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        {i > 0 && <ArrowRight size={12} style={{ color: INK.faint }} aria-hidden="true" />}
        <span><span style={{ fontFamily: MONO, color: INK.primary }}>{formatDate(s.date)}</span> {s.event}</span>
      </span>
    ))}
  </div>
);

const SourceList = ({ sources }) => {
  // Primary sources first, then coverage, each in file order.
  const ordered = [...sources.filter(s => s.kind === "primary"), ...sources.filter(s => s.kind !== "primary")];
  return (
    <div>
      <div style={{ fontSize: 11, color: INK.secondary, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600, marginBottom: 6 }}>
        References
      </div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 5 }}>
        {ordered.map(s => (
          <li key={s.url} style={{ display: "flex", gap: 8, alignItems: "baseline", fontSize: 12.5, lineHeight: 1.45, minWidth: 0 }}>
            <span style={{ flexShrink: 0, width: 66, fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em",
              color: s.kind === "primary" ? "#4ade80" : INK.muted }}>{SOURCE_KIND_TEXT[s.kind]}</span>
            <span style={{ minWidth: 0, overflowWrap: "anywhere" }}>
              <span style={{ color: INK.secondary }}>{s.publisher}{s.date ? `, ${formatDate(s.date)}` : ""}: </span>
              <ExtLink href={s.url}>{s.label}</ExtLink>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
};

const DealCard = ({ d }) => (
  <article aria-label={d.title} style={{ background: SURFACE, border: "1px solid #1e2028", borderRadius: 12, padding: "16px 20px" }}>
    <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start" }}>
      <div style={{ flex: "1 1 0", minWidth: 0 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
          <Badge color={TYPE_COLOR[d.type]}>{TYPE_TEXT[d.type]}</Badge>
          <Badge color="#94a3b8">{d.region}</Badge>
          <StatusPill info={d.statusInfo} />
          {d.statusInfo.checked && (
            <span style={{ fontSize: 11, color: d.statusInfo.recheck ? "#fbbf24" : INK.muted }}
              title={d.statusInfo.recheck ? `Not re-checked in over ${RECHECK_DAYS} days; it may have closed since.` : undefined}>
              {d.statusInfo.recheck && <AlertTriangle size={11} aria-hidden="true" style={{ verticalAlign: "-1px", marginRight: 3 }} />}
              {d.statusInfo.checked}{d.statusInfo.recheck && ` · re-check due (over ${RECHECK_DAYS} days)`}
            </span>
          )}
        </div>
        <h3 style={{ margin: "0 0 4px", fontSize: 15.5, fontWeight: 700, color: INK.primary, lineHeight: 1.35 }}>{d.title}</h3>
        <div style={{ fontSize: 12.5, color: INK.secondary, lineHeight: 1.5 }}>
          {d.parties.map((x, i) => (
            <span key={`${x.name}|${x.role}`}>{i > 0 && <span style={{ color: INK.faint }}> · </span>}
              <span style={{ color: INK.primary }}>{x.name}</span> <span style={{ color: INK.muted }}>({x.role})</span>
            </span>
          ))}
        </div>
      </div>
      <SizeFigure size={d.size} />
    </div>

    {d.size?.text && <div style={{ fontSize: 12, color: INK.muted, marginTop: 6 }}>{d.size.text}</div>}
    <p style={{ margin: "10px 0 0", fontSize: 13, color: "#cbd5e1", lineHeight: 1.6 }}>{d.summary}</p>
    {d.note && (
      <div style={{ display: "flex", gap: 7, alignItems: "flex-start", marginTop: 8, fontSize: 12, color: INK.secondary, lineHeight: 1.5 }}>
        <Info size={13} style={{ color: "#60a5fa", flexShrink: 0, marginTop: 2 }} /><span>{d.note}</span>
      </div>
    )}

    <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid #151820" }}><Timeline d={d} /></div>
    <div style={{ marginTop: 12 }}><SourceList sources={d.sources} /></div>
    <div style={{ marginTop: 10, fontSize: 11, color: INK.faint }}>
      <ShieldCheck size={11} style={{ verticalAlign: "-1px", marginRight: 4 }} />Facts checked against the primary sources on {formatDate(d.verified)}
    </div>
  </article>
);

const Stat = ({ label, value, sub }) => (
  <div style={{ background: SURFACE, border: "1px solid #1e2028", borderRadius: 10, padding: "14px 16px", minWidth: 0 }}>
    <div style={{ fontSize: 11, color: INK.secondary, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600 }}>{label}</div>
    <div style={{ fontSize: 24, fontWeight: 700, color: INK.primary, fontFamily: MONO, margin: "6px 0 2px" }}>{value}</div>
    {sub && <div style={{ fontSize: 11.5, color: INK.muted, lineHeight: 1.45 }}>{sub}</div>}
  </div>
);

const Chip = ({ active, onClick, color = "#3b82f6", children }) => (
  <button type="button" onClick={onClick} aria-pressed={active}
    style={{ background: active ? color + "22" : "transparent", border: `1px solid ${active ? color : "#334155"}`, borderRadius: 20,
      padding: "5px 14px", fontSize: 12, color: active ? INK.primary : INK.secondary, cursor: "pointer", fontWeight: 600, whiteSpace: "nowrap" }}>
    {children}
  </button>
);

const VettingPanel = ({ view }) => {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: 12, padding: "10px 12px", background: "#0f1520", border: "1px solid #1e3a5f", borderRadius: 8,
      fontSize: 12, color: INK.secondary, lineHeight: 1.55 }}>
      <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open}
        style={{ background: "transparent", border: 0, padding: 0, cursor: "pointer", color: INK.primary, fontSize: 12, fontWeight: 600,
          display: "inline-flex", alignItems: "center", gap: 6 }}>
        <ShieldCheck size={14} style={{ color: "#60a5fa" }} />How deals are vetted
        {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      </button>
      {open && <>
        <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>{view.vetting.map((v, i) => <li key={i}>{v}</li>)}</ul>
        {view.excluded.length > 0 && (
          <div style={{ marginTop: 8 }}>
            <strong style={{ color: INK.primary }}>Seen but not listed:</strong>
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {view.excluded.map((x, i) => <li key={i}>{x.title}{x.date ? ` (${formatDate(x.date)})` : ""}: <span style={{ color: INK.muted }}>{x.reason}</span></li>)}
            </ul>
          </div>
        )}
      </>}
    </div>
  );
};

// Shown only if an entry in data/deals.json breaks the vetting rules (CI
// should have caught it); names it so it can be fixed, never renders it.
const Rejected = ({ rejected }) => !rejected.length ? null : (
  <div style={{ display: "flex", gap: 8, alignItems: "flex-start", background: "#14120c", border: "1px solid #fbbf2433", borderRadius: 8,
    padding: "9px 12px", fontSize: 12, color: INK.secondary, lineHeight: 1.5 }}>
    <AlertTriangle size={14} style={{ color: "#fbbf24", flexShrink: 0, marginTop: 1 }} />
    <span>
      <strong style={{ color: INK.primary }}>{rejected.length} {rejected.length === 1 ? "entry" : "entries"} held back</strong> for failing vetting:{" "}
      {rejected.map(r => `${r.id} (${r.problems.join("; ")})`).join(" · ")}
    </span>
  </div>
);

export default function DealsSection({ data, error }) {
  const [type, setType] = useState("all");
  const [status, setStatus] = useState("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("recent");
  const view = useMemo(() => buildDealsView(data, { type, status, query, sort, today: today() }), [data, type, status, query, sort]);
  const s = view.stats;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ background: SURFACE, border: "1px solid #1e2028", borderRadius: 12, padding: "18px 22px" }}>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: INK.primary, display: "flex", alignItems: "center", gap: 9 }}>
          <Handshake size={20} /> Deals Tracker
        </h2>
        <div style={{ fontSize: 13, color: INK.secondary, marginTop: 6, lineHeight: 1.55, maxWidth: 860 }}>
          {view.scope || "Vetted life & annuity reinsurance transactions."} Every deal is checked against a primary source and links to it,
          with independent coverage alongside.
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: INK.secondary, marginTop: 8, flexWrap: "wrap" }}>
          <Clock size={13} /><span>Last reviewed {formatDate(view.updated)}</span>
          <span style={{ color: INK.faint }}>|</span>
          <span>Curated by hand in <code style={{ color: INK.primary, fontSize: 11.5 }}>data/deals.json</code></span>
        </div>
        <VettingPanel view={view} />
      </div>

      {/* App stores every file's data (and errors) only once all files have
          loaded, so "no data, no error" means still loading, not missing. */}
      {!data && !error && (
        <div style={{ padding: 24, color: INK.secondary, fontSize: 13 }}>
          <Loader size={16} style={{ verticalAlign: "middle", marginRight: 8, animation: "spin 1s linear infinite" }} />Loading deals…
        </div>
      )}
      {!data && error && (
        <div style={{ background: SURFACE, border: "1px solid #1e2028", borderRadius: 12, padding: "16px 20px", fontSize: 13, color: INK.secondary }}>
          <AlertTriangle size={14} style={{ verticalAlign: "middle", marginRight: 6, color: "#fbbf24" }} />
          Deals file not found{error ? ` (${error})` : ""}. It ships with the site build from data/deals.json.
        </div>
      )}

      {data && <>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 190px), 1fr))", gap: 12 }}>
          <Stat label="Deals tracked" value={s.total} sub="Signed or completed, each with a primary source" />
          <Stat label="Closed" value={s.closed} sub="Completion confirmed by a source" />
          <Stat label="Pending" value={s.pending} sub="Signed; awaiting approvals or closing" />
          <Stat label="Liabilities reinsured" value={formatUsdBn(s.liabilitiesUsdBn)}
            sub={`Reserves and liabilities in ${s.liabilitiesDeals} closed deals with a USD figure; excludes account values and prices`} />
        </div>

        <Rejected rejected={view.rejected} />

        <div style={{ background: SURFACE, border: "1px solid #1e2028", borderRadius: 12, padding: "14px 18px", display: "flex", flexDirection: "column", gap: 10 }}>
          <div role="group" aria-label="Deal type" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <Chip active={type === "all"} onClick={() => setType("all")}>All types <span style={{ color: INK.muted }}>{view.total}</span></Chip>
            {Object.entries(TYPE_TEXT).filter(([k]) => view.typeCounts[k]).map(([k, label]) => (
              <Chip key={k} active={type === k} color={TYPE_COLOR[k]} onClick={() => setType(k)}>
                {label} <span style={{ color: INK.muted }}>{view.typeCounts[k]}</span>
              </Chip>
            ))}
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
            <div role="group" aria-label="Status" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <Chip active={status === "all"} onClick={() => setStatus("all")}>Any status</Chip>
              {Object.entries(STATUS_TEXT).filter(([k]) => view.statusCounts[k]).map(([k, label]) => (
                <Chip key={k} active={status === k} color={STATUS_STYLE[k].color} onClick={() => setStatus(k)}>
                  {label} <span style={{ color: INK.muted }}>{view.statusCounts[k]}</span>
                </Chip>
              ))}
            </div>
            <label style={{ flex: "1 1 220px", display: "flex", alignItems: "center", gap: 7, border: "1px solid #334155", borderRadius: 8, padding: "5px 10px", minWidth: 0 }}>
              <Search size={14} style={{ color: INK.muted, flexShrink: 0 }} aria-hidden="true" />
              <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search companies, publishers, terms…" aria-label="Search deals"
                style={{ flex: 1, minWidth: 0, background: "transparent", border: 0, outline: "none", color: INK.primary, fontSize: 12.5, fontFamily: "inherit" }} />
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: INK.secondary }}>
              Sort
              <select value={sort} onChange={e => setSort(e.target.value)}
                style={{ background: "#12141a", color: INK.primary, border: "1px solid #334155", borderRadius: 6, padding: "4px 6px", fontSize: 12, fontFamily: "inherit" }}>
                {Object.entries(SORTS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </select>
            </label>
          </div>
          <div style={{ fontSize: 12, color: INK.muted }}>Showing {view.deals.length} of {view.total}</div>
        </div>

        {view.deals.length === 0
          ? <div style={{ padding: "18px 4px", fontSize: 13, color: INK.muted }}>No deals match these filters.</div>
          : view.deals.map(d => <DealCard key={d.id} d={d} />)}
      </>}
    </div>
  );
}

/** Overview card: the latest few deals, each linking to its primary source. */
export function DealsTile({ data, onOpen }) {
  const deals = useMemo(() => recentDeals(data, 5, today()), [data]);
  if (!deals.length) return null;
  return (
    <div style={{ background: SURFACE, border: "1px solid #1e2028", borderRadius: 10, overflow: "hidden" }}>
      <div style={{ padding: "14px 22px", borderBottom: "1px solid #1e2028", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: INK.primary }}>
          <Handshake size={15} style={{ verticalAlign: "middle", marginRight: 6 }} /> Recent Deals
        </h3>
        <button type="button" onClick={onOpen} style={{ background: "transparent", border: "none", color: "#60a5fa", fontSize: 12, cursor: "pointer", fontWeight: 600 }}>
          All <ChevronRight size={13} style={{ verticalAlign: "middle" }} />
        </button>
      </div>
      {deals.map(d => {
        const primary = d.sources.find(x => x.kind === "primary");
        const st = STATUS_STYLE[d.statusInfo.tone] || STATUS_STYLE.pending;
        return (
          <div key={d.id} style={{ padding: "10px 22px", borderBottom: "1px solid #151820", display: "flex", gap: 14, alignItems: "baseline", justifyContent: "space-between" }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 3, flexWrap: "wrap" }}>
                <Badge color={TYPE_COLOR[d.type]}>{TYPE_TEXT[d.type]}</Badge>
                <span style={{ fontSize: 11, color: INK.secondary, display: "inline-flex", alignItems: "center", gap: 4 }}>
                  <st.Icon size={11} style={{ color: st.color }} aria-hidden="true" />{STATUS_TEXT[d.status]}
                </span>
                <span style={{ fontSize: 11, color: INK.muted }}>{formatDate(d.activity)}</span>
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.4 }}>
                <ExtLink href={primary.url} style={{ color: INK.primary }}>{d.title}</ExtLink>
              </div>
            </div>
            <span style={{ fontFamily: MONO, fontSize: 13, color: d.size?.usd_bn != null ? INK.primary : INK.faint, whiteSpace: "nowrap" }}>
              {d.size?.usd_bn != null ? formatUsdBn(d.size.usd_bn) : "—"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
