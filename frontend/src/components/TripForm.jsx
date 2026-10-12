import { useState } from "react";
import PlaceInput from "./PlaceInput.jsx";
import { localInputToIso, nextQuarterHour, toLocalInput } from "../lib/format.js";

const EXAMPLES = [
  { o: { label: "Chicago, Illinois, US", lat: 41.8781, lon: -87.6298 }, d: { label: "Denver, Colorado, US", lat: 39.7392, lon: -104.9903 } },
  { o: { label: "Dallas, Texas, US", lat: 32.7767, lon: -96.797 }, d: { label: "Atlanta, Georgia, US", lat: 33.749, lon: -84.388 } },
  { o: { label: "Seattle, Washington, US", lat: 47.6062, lon: -122.3321 }, d: { label: "Salt Lake City, Utah, US", lat: 40.7608, lon: -111.891 } },
];

export default function TripForm({ onSubmit, loading }) {
  const [origin, setOrigin] = useState(null);
  const [destination, setDestination] = useState(null);
  const [departure, setDeparture] = useState(() => toLocalInput(nextQuarterHour()));
  const [load, setLoad] = useState("38000");
  const [intervalMi, setIntervalMi] = useState(25);
  const [hos, setHos] = useState(true);
  const [error, setError] = useState("");

  const min = toLocalInput(new Date(Date.now() - 30 * 60e3));
  const max = toLocalInput(new Date(Date.now() + 7 * 24 * 3600e3));

  const submit = (e) => {
    e.preventDefault();
    if (!origin || !destination) return setError("Pick an origin and a destination from the suggestions.");
    const lb = Number(load);
    if (!Number.isFinite(lb) || lb < 0 || lb > 80000) return setError("Load weight must be between 0 and 80,000 lb.");
    if (!departure) return setError("Choose a departure date and time.");
    setError("");
    onSubmit({
      origin,
      destination,
      departure: localInputToIso(departure),
      load_weight_lb: lb,
      interval_mi: intervalMi,
      apply_hos: hos,
    });
  };

  const useExample = (ex) => {
    setOrigin(ex.o);
    setDestination(ex.d);
  };

  return (
    <form className="trip-form" onSubmit={submit} noValidate>
      <PlaceInput label="From" value={origin} onChange={setOrigin} placeholder="City, address or lat, lon" />
      <PlaceInput label="To" value={destination} onChange={setDestination} placeholder="City, address or lat, lon" />
      <p className="examples">
        Try{" "}
        {EXAMPLES.map((ex, i) => (
          <button type="button" key={i} className="link" onClick={() => useExample(ex)}>
            {ex.o.label.split(",")[0]} to {ex.d.label.split(",")[0]}
          </button>
        ))}
      </p>

      <div className="row">
        <div className="field">
          <label htmlFor="departure">Departure</label>
          <input id="departure" type="datetime-local" value={departure} min={min} max={max} onChange={(e) => setDeparture(e.target.value)} required />
        </div>
        <div className="field narrow">
          <label htmlFor="load">Load (lb)</label>
          <input id="load" type="number" inputMode="numeric" min="0" max="80000" step="500" value={load} onChange={(e) => setLoad(e.target.value)} required />
        </div>
      </div>

      <fieldset className="field">
        <legend>Weather checkpoint every</legend>
        <div className="segmented" role="radiogroup">
          {[10, 25, 50].map((n) => (
            <label key={n} className={intervalMi === n ? "on" : ""}>
              <input type="radio" name="interval" value={n} checked={intervalMi === n} onChange={() => setIntervalMi(n)} />
              {n} mi
            </label>
          ))}
        </div>
      </fieldset>

      <label className="check">
        <input type="checkbox" checked={hos} onChange={(e) => setHos(e.target.checked)} />
        Include hours-of-service breaks in ETAs
      </label>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <button className="primary" type="submit" disabled={loading}>
        {loading ? "Checking routes and forecasts…" : "Find safest route"}
      </button>
    </form>
  );
}
