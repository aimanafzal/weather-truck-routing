import { LEVELS, levelColor } from "../lib/risk.js";
import { fmtDuration, fmtMiles, fmtTime } from "../lib/format.js";

/** Mile-by-mile strip of the risk along a route. */
export function RiskRibbon({ route, compact = false }) {
  const total = route.distance_mi || 1;
  return (
    <div className={`ribbon${compact ? " compact" : ""}`} role="img" aria-label={ribbonLabel(route)}>
      {route.checkpoints.map((cp) => {
        const [a, b] = cp.span_mi;
        if (b <= a) return null;
        return (
          <span
            key={cp.index}
            style={{ flexGrow: b - a, flexBasis: 0, background: levelColor(cp.risk?.level) }}
            title={`Mile ${cp.mile}: ${cp.risk?.level ?? "no forecast"}`}
          />
        );
      })}
      {!compact && (
        <span className="ribbon-scale" aria-hidden="true">
          <span>0</span>
          <span>{Math.round(total)} mi</span>
        </span>
      )}
    </div>
  );
}

function ribbonLabel(route) {
  const parts = LEVELS.filter((l) => route.stats.miles_by_level[l] > 0).map((l) => `${Math.round(route.stats.miles_by_level[l])} miles ${l}`);
  return `Risk along ${route.name}: ${parts.join(", ")}`;
}

export default function RouteCard({ route, selected, onSelect }) {
  const m = route.stats.miles_by_level;
  const flagged = ["No Travel", "Severe", "High"].filter((l) => m[l] > 0);
  return (
    <button
      type="button"
      className={`route-card${selected ? " selected" : ""}${route.recommended ? " best" : ""}`}
      onClick={() => onSelect(route.id)}
      aria-pressed={selected}
    >
      <div className="route-top">
        <span className="shield" aria-hidden="true">
          {route.id}
        </span>
        <div className="route-title">
          <strong>{route.name}</strong>
          <span className="via">{route.via ? `via ${route.via}` : "Alternate route"}</span>
        </div>
        {route.recommended && <span className="best-plate">Recommended</span>}
      </div>

      <dl className="route-figures">
        <div>
          <dt>Distance</dt>
          <dd>{fmtMiles(route.distance_mi)}</dd>
        </div>
        <div>
          <dt>Travel time</dt>
          <dd>{fmtDuration(route.travel_time_s)}</dd>
        </div>
        <div>
          <dt>Arrives</dt>
          <dd>{fmtTime(route.arrival)}</dd>
        </div>
        <div>
          <dt>Avg risk</dt>
          <dd>{route.stats.avg_risk == null ? "n/a" : route.stats.avg_risk.toFixed(2)}</dd>
        </div>
      </dl>

      <RiskRibbon route={route} />

      <p className="route-flags">
        {flagged.length === 0 && route.stats.unknown_mi === 0 && <span>No High, Severe or No Travel miles</span>}
        {flagged.map((l) => (
          <span key={l} className="flag">
            <i style={{ background: levelColor(l) }} />
            {fmtMiles(m[l])} {l}
          </span>
        ))}
        {route.stats.unknown_mi > 0 && <span className="flag">{fmtMiles(route.stats.unknown_mi)} beyond forecast</span>}
      </p>
    </button>
  );
}
