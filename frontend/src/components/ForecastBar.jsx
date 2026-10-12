import { useEffect, useRef } from "react";
import { LEVELS, LEVEL_COLORS, METRICS } from "../lib/risk.js";

const fmt = new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });

export default function ForecastBar({ heatmap, hour, setHour, metric, setMetric, showHeat, setShowHeat, playing, setPlaying, departure }) {
  const raf = useRef(0);

  // Play: advance ~3 forecast hours per second, smoothly (fractional hours are interpolated).
  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    const tick = (now) => {
      const dt = (now - last) / 1000;
      last = now;
      setHour((h) => {
        const next = h + dt * 3;
        if (next >= heatmap.hours) {
          setPlaying(false);
          return heatmap.hours;
        }
        return next;
      });
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [playing, heatmap.hours, setHour, setPlaying]);

  const start = Date.parse(heatmap.start);
  const at = new Date(start + hour * 3600e3);
  const sinceDep = (at - Date.parse(departure)) / 3600e3;
  const m = METRICS[metric];
  const ticks = [0, 12, 24, 36, 48];

  return (
    <div className="forecast-bar">
      <div className="fb-row">
        <button
          type="button"
          className="play"
          onClick={() => {
            if (!playing && hour >= heatmap.hours) setHour(0);
            setPlaying(!playing);
          }}
          aria-label={playing ? "Pause forecast animation" : "Play forecast animation"}
        >
          {playing ? (
            <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="2" width="3.5" height="12" /><rect x="9.5" y="2" width="3.5" height="12" /></svg>
          ) : (
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2l10 6-10 6z" /></svg>
          )}
        </button>
        <div className="fb-time" aria-live="polite">
          <strong>{fmt.format(at)}</strong>
          <span>{sinceDep >= 0 ? `${sinceDep.toFixed(sinceDep % 1 ? 1 : 0)} h after departure` : "before departure"}</span>
        </div>
        <label className="fb-toggle">
          <input type="checkbox" checked={showHeat} onChange={(e) => setShowHeat(e.target.checked)} />
          Heatmap
        </label>
        <select value={metric} onChange={(e) => setMetric(e.target.value)} aria-label="Heatmap layer" disabled={!showHeat}>
          {Object.entries(METRICS).map(([k, v]) => (
            <option key={k} value={k}>
              {v.label}
            </option>
          ))}
        </select>
      </div>
      <input
        className="fb-slider"
        type="range"
        min="0"
        max={heatmap.hours}
        step="0.25"
        value={hour}
        onChange={(e) => {
          setPlaying(false);
          setHour(Number(e.target.value));
        }}
        aria-label="Forecast hour"
        aria-valuetext={`${fmt.format(at)}, ${Math.round(hour)} hours from departure hour`}
      />
      <div className="fb-ticks" aria-hidden="true">
        {ticks.map((t) => (
          <span key={t} style={{ left: `${(t / heatmap.hours) * 100}%` }}>
            +{t}h
          </span>
        ))}
      </div>
      <div className="legend" aria-label="Risk colour legend">
        {LEVELS.map((l, i) => (
          <span key={l}>
            <i style={{ background: LEVEL_COLORS[l] }} />
            {l}
            {m.edges && <em>{i === 0 ? `<${m.edges[0]}` : i === 4 ? `${l === "No Travel" && metric === "wind" ? "≥" : ">"}${m.edges[3]}` : `${m.edges[i - 1]}+`}</em>}
          </span>
        ))}
        {m.unit && <span className="unit">{m.unit}</span>}
      </div>
    </div>
  );
}
