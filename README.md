# Weather-Aware Truck Routing

A React + Django web app that helps a truck driver pick the safest route between two places, using the
weather the truck will actually meet at each point along the way, the load weight, and travel time.

- Enter an origin, a destination, a departure time and a load weight.
- Get **3 route options**, each with weather **checkpoints every 10, 25 or 50 miles**, sampled at the
  truck's **estimated arrival time** at that checkpoint.
- Every checkpoint gets a risk level (Low → No Travel) from the brief's wind/rain/snow and load rules.
- The app **recommends a route**: fewest No Travel miles, then fewest Severe, then fewest High miles,
  then lowest average risk, then shortest travel time.
- A map shows all routes, checkpoints, ETAs, risk levels, rest stops and route summaries, plus a
  **weather heatmap of the trip corridor** with a **0–48 hour forecast slider** (and play button)
  that moves a truck marker along the selected route.

No API keys are needed: routing is [OSRM](https://project-osrm.org), weather is
[Open-Meteo](https://open-meteo.com), place search is [Photon](https://photon.komoot.io) (OpenStreetMap),
and map tiles are CARTO/OpenStreetMap.

---

## Run it locally

Requirements: Python 3.10+ and Node 18+.

```bash
# 1. Backend (terminal 1)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
DJANGO_DEBUG=1 python manage.py runserver 8000

# 2. Frontend with hot reload (terminal 2) — proxies /api to :8000
cd frontend
npm install
npm run dev            # open http://localhost:5173
```

Single-server mode (what production runs): `cd frontend && npm run build`, then start Django and open
http://localhost:8000 — Django serves the built app from `frontend/dist`.

**Offline demo:** set `PROVIDER_MODE=fake` on the backend to use deterministic synthetic routes and a
storm cell that drifts east across the Midwest. Useful with no internet, and it is what the tests use.

### Tests

```bash
cd backend && pytest          # 64 tests: risk rules, ETAs/HOS, sampling, ranking, API parsing, endpoints
cd frontend && npm test       # risk scale, colour ramp, track interpolation, time formatting
```

## Deploy (ready to host)

The repo builds into **one Docker image**: Node builds the React app, then a slim Python image runs
Django + Gunicorn and serves both the API and the static app. Health check: `GET /api/health`.

**Render (free tier, ~3 minutes)**
1. Push this folder to a GitHub repository.
2. In Render: **New → Blueprint**, select the repo. `render.yaml` creates the web service and
   generates `DJANGO_SECRET_KEY`.
3. Open the `*.onrender.com` URL.

**Railway / Fly.io / any Docker host**: deploy the `Dockerfile`. It listens on `$PORT` (default 8000).
Set `DJANGO_SECRET_KEY`, and add your domain to `DJANGO_ALLOWED_HOSTS` if it isn't
`*.onrender.com`, `*.railway.app` or `*.fly.dev`.

```bash
docker build -t truck-routing .
docker run -p 8000:8000 -e DJANGO_SECRET_KEY=change-me truck-routing   # http://localhost:8000
```

**Split hosting (optional)**: host `frontend/` on Vercel/Netlify with `VITE_API_BASE=https://your-api`
at build time, and set `CORS_ALLOWED_ORIGINS=https://your-frontend` on the API.

All settings are environment variables — see `.env.example`.

---

## How it works

```
Browser (React + Leaflet)                     Django API                          Third-party APIs
 trip form ──POST /api/plan──────────────▶  validate input
                                            find_route_options() ───────────▶  OSRM (alternatives + via points)
                                            build_timeline()  (65 mph cap, HOS stops)
                                            checkpoints every N mi + ETA
                                            one batched forecast fetch ─────▶  Open-Meteo hourly (wind, rain, snow)
                                            weather at each ETA → risk rules
                                            miles per level → recommend()
 map, cards, heatmap  ◀────────JSON──────── routes + checkpoints + heatmap grid
```

### 1. Three route options
OSRM is asked for alternatives. The public server often returns only one or two, so the backend tops
up to three by routing through **via points** offset either side of the direct line (18% and then 35%
of the crow-flies distance). Candidates are kept only if they are genuinely different (less than ~85–90% of
their length within 1.5 miles of an existing option) and not absurd detours (at most 1.6× the
fastest route's distance and time).

### 2. Truck ETAs
OSRM gives per-segment car travel times. For a truck each segment is slowed to at most
**65 mph** (`TRUCK_MAX_MPH`). With "hours-of-service breaks" on (default), a simplified FMCSA rule set is
applied: a **30-minute break after 8 hours of driving** and a **10-hour rest after 11 hours of driving**.
These stops shift every later ETA, show on the map, and are included in travel time.

### 3. Checkpoints and weather at arrival time
Checkpoints are dropped at mile 0, every 10/25/50 miles, and at the destination. Each gets the ETA from
the timeline. Forecasts for every checkpoint (snapped to a ~3-mile grid so overlapping routes share
lookups) and every heatmap point are fetched in **one batched Open-Meteo request set** covering
departure → max(departure + 48 h, last arrival). Values are **linearly interpolated between hourly
forecasts** at the exact ETA.

| Field | Source |
|---|---|
| Wind (mph) | `wind_speed_10m` (sustained; gusts shown for context) |
| Rain (in/hr) | `rain + showers` (liquid precipitation in the hour) |
| Snow (in/hr) | `snowfall` |

### 4. Risk rules (`backend/routing/services/risk.py`)

| Condition | Low | Moderate | High | Severe | No Travel |
|---|---|---|---|---|---|
| Wind | <25 mph | 25–34 | 35–44 | 45–54 | ≥55 |
| Rain | <0.10 in/hr | 0.10–0.25 | 0.25–0.50 | 0.50–1.00 | >1.00 |
| Snow | <0.5 in/hr | 0.5–1.0 | 1.0–2.0 | 2.0–3.0 | >3.0 |

A checkpoint's level is the **worst of the three**. Load rules then raise it (never lower it):
wind ≥55 → No Travel for any load; wind 45–54 with load >30,000 lb → No Travel; wind 35–44 with load
>40,000 lb → Severe. Boundaries: a value equal to a band's lower bound is in that band (wind 35 = High,
rain 0.25 = High); top bands follow the brief's operators (wind ≥55, rain >1.00, snow >3.0).

### 5. Miles per risk level and the recommendation
Each checkpoint represents the stretch of road nearest to it (half-way to its neighbours), so the miles
per level always add up to the route length. Average risk is the distance-weighted mean on a
0 (Low) – 4 (No Travel) scale.

Routes are ranked lexicographically, exactly in the brief's order, with one addition at the top:

1. Fewest **No Travel** miles *(added: a No Travel mile is strictly worse than a Severe one)*
2. Fewest **Severe** miles
3. Fewest **High** miles
4. Lowest **average risk**
5. Shortest **travel time**

The UI states which criterion decided it ("Route B is recommended — fewer Severe miles: 0.0 mi vs
42.5 mi on Route A") and warns when even the best route has No Travel miles.

### 6. Corridor heatmap and the 0–48 h slider
The backend samples a band of points along and either side of every route (≤180 points, spacing
scaled to trip length) and returns hourly wind/rain/snow plus a continuous 0–4 risk value for 49 hours.
The frontend draws it with a small custom Leaflet canvas layer: inverse-distance interpolation onto a
coarse pixel grid, coloured on the risk ramp, faded out away from the corridor, then upscaled with
smoothing. A redraw takes a few milliseconds, so the slider moves in 15-minute steps (interpolated between
hourly values) and the play button animates continuously. Layers: overall risk (includes load
rules), wind, rain, snow — each coloured by the same risk bands.

---

## API

`POST /api/plan`
```json
{
  "origin": {"lat": 41.8781, "lon": -87.6298, "label": "Chicago, IL"},
  "destination": "Denver, CO",
  "departure": "2026-10-13T06:00:00-05:00",
  "load_weight_lb": 42000,
  "interval_mi": 25,
  "apply_hos": true
}
```
`origin`/`destination` accept `{lat, lon, label}`, `"lat, lon"`, or free text (geocoded). Departure must
include a UTC offset and be within the next 7 days. Response: `routes[]` (geometry, segments coloured by
risk, checkpoints with ETA/weather/risk/reasons, HOS stops, a time→position track, stats, rank),
`recommended_id`, `recommendation {text, deciding_factor, warning}`, and `heatmap`.

`GET /api/geocode?q=denver` → `{results: [{label, lat, lon}]}` · `GET /api/health`

Errors return `{ "error": "..." }` with 400 (bad input) or 502 (upstream API failure).

## Project layout

```
backend/
  config/                 settings (env-driven), urls, wsgi
  routing/services/
    geo.py                distances, polyline decoding, interpolation, simplification
    risk.py               the brief's risk + load rules
    providers.py          OSRM / Open-Meteo / Photon clients (+ offline fakes), caching, retries
    planner.py            alternatives, truck timeline, checkpoints, weather sampling, ranking, heatmap
  routing/views.py        /api/plan, /api/geocode, /api/health, SPA fallback
  routing/tests/          pytest suite
frontend/src/
  App.jsx                 page state
  components/             TripForm, PlaceInput, RouteCard (+ risk ribbon), CheckpointTable, MapView, ForecastBar
  lib/                    api client, risk colours/thresholds, heatmap canvas layer, formatting
Dockerfile, render.yaml, Procfile, .env.example
```

## Assumptions and limits

- Routing uses OSRM's car profile with a truck speed cap; it does not know truck-specific restrictions
  (bridge heights, hazmat, weight limits). A truck routing API (HERE, PTV, Trimble) could replace
  `OsrmRouter` behind the same interface.
- The public OSRM, Open-Meteo and Photon endpoints are free and rate-limited (Open-Meteo: 10,000
  location-calls/day). Responses are cached in memory (routes 1 h, forecasts 30 min). For heavy use, set
  `OPEN_METEO_API_KEY` + `OPEN_METEO_URL=https://customer-api.open-meteo.com`, or point `OSRM_URL` at a
  self-hosted OSRM.
- Forecasts reach ~15 days, so departures are limited to the next 7 days; any checkpoint past the forecast
  horizon is shown as "beyond forecast" and excluded from the average.
- Times are shown in the browser's time zone.
