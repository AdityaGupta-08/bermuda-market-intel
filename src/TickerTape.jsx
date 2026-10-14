import { useEffect, useMemo, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import { buildTickerGroups, formatTapeItem } from "./tickerTape.js";

/* Scrolling tape under the header: yields and commodity prices grouped by
   country, crawling continuously like a news-channel ticker. Two identical
   copies scroll left by exactly one copy's width, so the loop is seamless.
   It keeps moving even when the OS asks for reduced motion (the tape is the
   point); the pause button, mouse hover and keyboard focus stop it. Taps and
   clicks do not, so it never gets stuck paused on a phone. */

// Same convention as the rest of the dashboard: up red, down green.
const DIR = {
  1: { color: "#f87171", mark: "▲" },
  [-1]: { color: "#4ade80", mark: "▼" },
  0: { color: "#94a3b8", mark: "■" },
};
const FLAG_TEXT = {
  held: "held at the previous value (one-tenor jump rejected)",
  interpolated: "interpolated, no market quote this run",
  cached: "carried forward from an earlier run",
};
const PX_PER_SECOND = 55;

const CSS = `
.tape { display: flex; flex-shrink: 0; height: 34px; background: #07090d; border-bottom: 1px solid #1a1d23; }
.tape-viewport { position: relative; flex: 1; min-width: 0; overflow: hidden;
  -webkit-mask-image: linear-gradient(90deg, transparent, #000 28px, #000 calc(100% - 28px), transparent);
          mask-image: linear-gradient(90deg, transparent, #000 28px, #000 calc(100% - 28px), transparent); }
.tape-track { display: flex; width: max-content; height: 100%; animation: tape-scroll linear infinite; will-change: transform; }
.tape.is-paused .tape-track, .tape-viewport:has(:focus-visible) .tape-track { animation-play-state: paused; }
@media (hover: hover) { .tape-viewport:hover .tape-track { animation-play-state: paused; } }
.tape-copy, .tape-group { display: flex; align-items: center; height: 100%; }
.tape-group { gap: 16px; padding: 0 24px 0 14px; border-right: 1px solid #1a1d23; }
.tape-code { border: 1px solid; border-radius: 4px; padding: 1px 6px; font: 700 11px 'JetBrains Mono', monospace; letter-spacing: 0.06em; cursor: pointer; }
.tape-code:focus-visible, .tape-toggle:focus-visible { outline: 2px solid #60a5fa; outline-offset: 2px; }
.tape-item { display: inline-flex; align-items: baseline; gap: 6px; white-space: nowrap; font: 12px 'JetBrains Mono', monospace; }
.tape-toggle { flex-shrink: 0; width: 34px; display: flex; align-items: center; justify-content: center; background: transparent;
  border: 0; border-left: 1px solid #1a1d23; color: #94a3b8; cursor: pointer; }
.tape-toggle:hover { color: #f1f5f9; background: #11141a; }
@keyframes tape-scroll { from { transform: translateX(0); } to { transform: translateX(-50%); } }
`;

export default function TickerTape({ data, onNavigate }) {
  const groups = useMemo(() => buildTickerGroups(data), [data]);
  const copyRef = useRef(null);
  const [duration, setDuration] = useState(60);
  const [paused, setPaused] = useState(false);

  // Constant reading speed: the loop takes longer when there is more to read.
  useEffect(() => {
    const el = copyRef.current;
    if (!el) return undefined;
    const update = () => setDuration(Math.max(20, el.offsetWidth / PX_PER_SECOND));
    update();
    if (typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [groups]);

  if (!groups.length) return null;

  const copy = hidden => (
    <div className="tape-copy" ref={hidden ? undefined : copyRef} aria-hidden={hidden ? "true" : undefined}>
      {groups.map(g => (
        <div key={g.key} className="tape-group">
          <button type="button" className="tape-code" tabIndex={hidden ? -1 : 0} onClick={() => onNavigate?.(g.page)}
            title={`${g.label} — open page`} style={{ color: g.color, borderColor: `${g.color}66`, background: `${g.color}1a` }}>
            {g.code}
          </button>
          {g.items.map(it => {
            const f = formatTapeItem(it);
            const d = DIR[f.dir];
            return (
              <span key={it.id} className="tape-item" title={it.flag ? `${it.label}: ${FLAG_TEXT[it.flag]}` : undefined}>
                <span style={{ color: "#94a3b8" }}>{it.label}</span>
                <span style={{ color: it.flag ? "#94a3b8" : "#f1f5f9", fontWeight: 600 }}>{f.value}{it.flag ? "*" : ""}</span>
                {f.change && <span style={{ color: d.color }}>{d.mark}{f.change}</span>}
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );

  return (
    <div className={`tape${paused ? " is-paused" : ""}`} role="region" aria-label="Market tape: yields and commodity prices by country">
      <style>{CSS}</style>
      <div className="tape-viewport">
        <div className="tape-track" style={{ animationDuration: `${duration}s` }}>
          {copy(false)}
          {copy(true)}
        </div>
      </div>
      <button type="button" className="tape-toggle" onClick={() => setPaused(p => !p)} aria-pressed={paused}
        aria-label={paused ? "Resume market tape" : "Pause market tape"} title={paused ? "Resume" : "Pause"}>
        {paused ? <Play size={13} /> : <Pause size={13} />}
      </button>
    </div>
  );
}
