import { useCallback, useRef, useState } from "react";
import TripForm from "./components/TripForm.jsx";
import RouteCard from "./components/RouteCard.jsx";
import CheckpointTable from "./components/CheckpointTable.jsx";
import MapView from "./components/MapView.jsx";
import ForecastBar from "./components/ForecastBar.jsx";
import { planTrip } from "./lib/api.js";

export default function App() {
  const [result, setResult] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hour, setHour] = useState(0);
  const [metric, setMetric] = useState("risk");
  const [showHeat, setShowHeat] = useState(true);
  const [playing, setPlaying] = useState(false);
  const abort = useRef(null);

  const submit = useCallback(async (payload) => {
    abort.current?.abort();
    abort.current = new AbortController();
    setLoading(true);
    setError("");
    setPlaying(false);
    try {
      const data = await planTrip(payload, abort.current.signal);
      setResult(data);
      setSelectedId(data.recommended_id);
      // Start the slider at the departure time.
      const offset = (Date.parse(data.request.departure) - Date.parse(data.heatmap.start)) / 3600e3;
      setHour(Math.max(0, Math.min(data.heatmap.hours, Math.round(offset * 4) / 4)));
    } catch (e) {
      if (e.name !== "AbortError") setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const selected = result?.routes.find((r) => r.id === selectedId);
  const ordered = result ? [...result.routes].sort((a, b) => a.rank - b.rank) : [];

  return (
    <div className="app">
      <aside className="panel">
        <header className="brand">
          <svg viewBox="0 0 32 32" aria-hidden="true" className="brand-mark">
            <rect width="32" height="32" rx="6" fill="#0B6E4F" />
            <path d="M7 22h18M9 22V12h9v10M18 15h4l3 4v3" stroke="#fff" strokeWidth="2.4" fill="none" strokeLinejoin="round" />
            <circle cx="12" cy="23" r="2" fill="#F2B705" />
            <circle cx="21" cy="23" r="2" fill="#F2B705" />
          </svg>
          <div>
            <h1>Weather-aware truck routing</h1>
            <p>Compare three routes by the weather the truck will actually drive through.</p>
          </div>
        </header>

        <TripForm onSubmit={submit} loading={loading} />

        {error && (
          <div className="alert" role="alert">
            <strong>Couldn't plan this trip.</strong> {error}
          </div>
        )}

        {result && (
          <section className="results" aria-live="polite">
            <div className={`verdict${result.recommendation.warning ? " warn" : ""}`}>
              <p>{result.recommendation.text}</p>
              {result.recommendation.warning && <p className="warning">{result.recommendation.warning}</p>}
            </div>
            <div className="route-list">
              {ordered.map((r) => (
                <RouteCard key={r.id} route={r} selected={r.id === selectedId} onSelect={setSelectedId} />
              ))}
            </div>
            <p className="muted small rank-note">
              Ranked by fewest No Travel, then Severe, then High-risk miles, then lowest average risk, then shortest travel time.
            </p>
            {selected && <CheckpointTable route={selected} />}
          </section>
        )}

        {!result && !loading && (
          <p className="empty muted">
            Enter a trip to see three route options, weather checkpoints along each one at the truck's arrival time, and a 48-hour forecast of the corridor.
          </p>
        )}
      </aside>

      <main className="map-area">
        <MapView result={result} selectedId={selectedId} onSelect={setSelectedId} hour={hour} metric={metric} showHeat={showHeat} />
        {loading && (
          <div className="map-loading" role="status">
            <span className="spinner" aria-hidden="true" />
            Getting routes and the forecast along each one
          </div>
        )}
        {result && (
          <ForecastBar
            heatmap={result.heatmap}
            departure={result.request.departure}
            hour={hour}
            setHour={setHour}
            metric={metric}
            setMetric={setMetric}
            showHeat={showHeat}
            setShowHeat={setShowHeat}
            playing={playing}
            setPlaying={setPlaying}
          />
        )}
      </main>
    </div>
  );
}
