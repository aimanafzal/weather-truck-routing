import { levelColor } from "../lib/risk.js";
import { fmtDuration, fmtTime } from "../lib/format.js";

export default function CheckpointTable({ route }) {
  const driving = fmtDuration(route.drive_time_s);
  const stops = route.stops.length;
  return (
    <section className="checkpoints" aria-label={`Checkpoints for ${route.name}`}>
      <h3>{route.name} checkpoints</h3>
      <p className="muted small">
        Weather is the forecast for when the truck reaches each point. Driving time {driving}
        {stops > 0 ? `, plus ${stops} hours-of-service stop${stops > 1 ? "s" : ""}.` : "."}
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Mile</th>
              <th scope="col">ETA</th>
              <th scope="col">Wind</th>
              <th scope="col">Rain</th>
              <th scope="col">Snow</th>
              <th scope="col">Risk</th>
            </tr>
          </thead>
          <tbody>
            {route.checkpoints.map((cp) => (
              <tr key={cp.index} title={cp.risk?.reasons.join("\n")}>
                <td>{cp.mile}</td>
                <td>{fmtTime(cp.eta)}</td>
                <td>{cp.weather ? `${Math.round(cp.weather.wind_mph)}` : "–"}</td>
                <td>{cp.weather ? cp.weather.rain_in_hr.toFixed(2) : "–"}</td>
                <td>{cp.weather ? cp.weather.snow_in_hr.toFixed(2) : "–"}</td>
                <td>
                  <span className="level-chip" style={{ "--c": levelColor(cp.risk?.level) }}>
                    {cp.risk?.level ?? "No data"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">Wind in mph, rain and snow in inches per hour.</p>
    </section>
  );
}
