"""Trip planning pipeline.

1. Get up to 3 distinct route options (OSRM alternatives, topped up with via-point detours).
2. Build a truck timeline for each route (65 mph cap + optional FMCSA hours-of-service stops).
3. Drop checkpoints every N miles and compute the truck's ETA at each.
4. Fetch hourly forecasts (one batched call for all checkpoints + heatmap corridor) and
   interpolate the weather at each checkpoint's ETA.
5. Classify risk, roll up miles per risk level, and pick the recommended route.
"""
from __future__ import annotations

import bisect
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from django.conf import settings

from . import geo, risk
from .providers import HourlySeries, ProviderError, RawRoute, get_router, get_weather

log = logging.getLogger(__name__)

HOUR = 3600.0
HEATMAP_HOURS = 48
ROUTE_LETTERS = "ABC"


# --------------------------------------------------------------------------- inputs


@dataclass
class TripRequest:
    origin: geo.LatLon
    destination: geo.LatLon
    departure: datetime  # tz-aware
    load_lb: float
    interval_mi: int = 25
    apply_hos: bool = True
    origin_label: str = "Origin"
    destination_label: str = "Destination"


# --------------------------------------------------------------------------- route alternatives


def find_route_options(origin: geo.LatLon, dest: geo.LatLon, wanted: int = 3) -> list[RawRoute]:
    router = get_router()
    routes = router.route([origin, dest], alternatives=wanted)
    if not routes:
        raise ProviderError("No drivable route found between these locations.")
    routes.sort(key=lambda r: r.duration_s)

    kept: list[RawRoute] = []
    for r in routes:
        if _is_distinct(r, kept):
            kept.append(r)
        if len(kept) == wanted:
            return kept

    # Top up with via-point detours either side of the direct line.
    fastest = kept[0]
    crow = geo.haversine_mi(origin, dest)
    brg = geo.bearing_deg(origin, dest)
    for frac, side in ((0.18, 1), (0.18, -1), (0.35, 1), (0.35, -1)):
        if len(kept) >= wanted:
            break
        offset = min(160.0, max(12.0, crow * frac))
        for along in (0.5,):
            base = geo.destination(origin, brg, crow * along)
            via = geo.destination(base, brg + 90 * side, offset)
            try:
                cand = router.route([origin, via, dest], alternatives=0)
            except ProviderError as exc:
                log.info("via candidate failed: %s", exc)
                continue
            if not cand:
                continue
            c = cand[0]
            if c.distance_m > fastest.distance_m * 1.6 or c.duration_s > fastest.duration_s * 1.6:
                continue
            if _is_distinct(c, kept, threshold=0.85):
                kept.append(c)
    return kept


def _is_distinct(r: RawRoute, kept: list[RawRoute], threshold: float = 0.9) -> bool:
    return all(geo.overlap_fraction(r.coords, k.coords) < threshold for k in kept)


# --------------------------------------------------------------------------- truck timeline


@dataclass
class Stop:
    drive_s: float  # driving seconds at which the stop starts
    duration_s: float
    kind: str  # "break" | "rest"


def hos_stops(total_drive_s: float, apply: bool) -> list[Stop]:
    """FMCSA property-carrying rules, simplified: 30-min break after 8 h of driving,
    10-h off-duty after 11 h of driving in a shift (which also resets the 8-h clock)."""
    if not apply:
        return []
    stops: list[Stop] = []
    shift_start = last_break = 0.0
    while True:
        next_break = last_break + 8 * HOUR
        shift_end = shift_start + 11 * HOUR
        if shift_end <= next_break:
            if shift_end >= total_drive_s:
                break
            stops.append(Stop(shift_end, 10 * HOUR, "rest"))
            shift_start = last_break = shift_end
        else:
            if next_break >= total_drive_s:
                break
            stops.append(Stop(next_break, 0.5 * HOUR, "break"))
            last_break = next_break
    return stops


def clock_seconds(drive_s: float, stops: list[Stop]) -> float:
    """Elapsed wall-clock seconds when the truck has driven `drive_s` seconds."""
    return drive_s + sum(s.duration_s for s in stops if s.drive_s < drive_s)


@dataclass
class Timeline:
    coords: list[geo.LatLon]
    cum_mi: list[float]
    cum_drive_s: list[float]
    stops: list[Stop]

    @property
    def total_mi(self) -> float:
        return self.cum_mi[-1]

    @property
    def drive_s(self) -> float:
        return self.cum_drive_s[-1]

    @property
    def travel_s(self) -> float:
        return clock_seconds(self.drive_s, self.stops) if self.stops else self.drive_s

    def drive_at(self, mile: float) -> float:
        return geo.interp_series(self.cum_mi, self.cum_drive_s, mile)

    def clock_at(self, mile: float) -> float:
        return clock_seconds(self.drive_at(mile), self.stops)

    def mile_at_drive(self, drive_s: float) -> float:
        return geo.interp_series(self.cum_drive_s, self.cum_mi, drive_s)


def build_timeline(raw: RawRoute, apply_hos: bool) -> Timeline:
    cum = geo.cumulative_miles(raw.coords)
    max_mph = settings.TRUCK_MAX_MPH
    drive = [0.0]
    for i, osrm_s in enumerate(raw.seg_seconds):
        miles = cum[i + 1] - cum[i]
        drive.append(drive[-1] + max(osrm_s, miles / max_mph * HOUR))
    return Timeline(raw.coords, cum, drive, hos_stops(drive[-1], apply_hos))


# --------------------------------------------------------------------------- checkpoints


def checkpoint_miles(total: float, interval: float) -> list[float]:
    marks = [0.0]
    m = interval
    while m < total - 0.5:
        marks.append(m)
        m += interval
    marks.append(total)
    return marks


def _weather_key(p: geo.LatLon) -> geo.LatLon:
    # 0.05° (~3 mi) grid: finer than the 10-mile minimum checkpoint spacing and comparable to
    # forecast-model resolution, while letting overlapping routes share one forecast lookup.
    return (round(round(p[0] / 0.05) * 0.05, 4), round(round(p[1] / 0.05) * 0.05, 4))


def sample_series(s: HourlySeries, ts: float) -> dict | None:
    if not s.times or ts < s.times[0] - HOUR or ts > s.times[-1] + HOUR:
        return None
    return {
        "wind_mph": round(geo.interp_series(s.times, s.wind, ts), 1),
        "gust_mph": round(geo.interp_series(s.times, s.gust, ts), 1),
        "rain_in_hr": round(geo.interp_series(s.times, s.rain, ts), 3),
        "snow_in_hr": round(geo.interp_series(s.times, s.snow, ts), 3),
    }


# --------------------------------------------------------------------------- heatmap corridor


def corridor_points(timelines: list[Timeline], max_points: int = 180) -> tuple[list[geo.LatLon], float]:
    """Sample points along and either side of every route (a ~4-spacing-wide band).
    Returns the points and their spacing in miles."""
    longest = max(t.total_mi for t in timelines)
    spacing = min(80.0, max(10.0, longest / 25))
    while True:
        pts = _corridor(timelines, spacing)
        if len(pts) <= max_points:
            return pts, spacing
        spacing *= 1.25


def _corridor(timelines: list[Timeline], spacing: float) -> list[geo.LatLon]:
    cell_deg = spacing * 0.8 / 69.0
    seen: dict[tuple[int, int], geo.LatLon] = {}
    for tl in timelines:
        n = max(2, int(tl.total_mi / spacing) + 1)
        for i in range(n + 1):
            m = tl.total_mi * i / n
            p = geo.interpolate_along(tl.coords, tl.cum_mi, m)
            ahead = geo.interpolate_along(tl.coords, tl.cum_mi, min(tl.total_mi, m + 1))
            behind = geo.interpolate_along(tl.coords, tl.cum_mi, max(0.0, m - 1))
            brg = geo.bearing_deg(behind, ahead)
            for k in (-2, -1, 0, 1, 2):
                q = geo.destination(p, brg + 90, k * spacing) if k else p
                key = (int(math.floor(q[0] / cell_deg)), int(math.floor(q[1] / cell_deg)))
                seen.setdefault(key, q)
    return list(seen.values())


# --------------------------------------------------------------------------- main entry


def plan_trip(req: TripRequest) -> dict:
    raw_routes = find_route_options(req.origin, req.destination)
    timelines = [build_timeline(r, req.apply_hos) for r in raw_routes]

    dep_ts = req.departure.timestamp()
    dep_hour = req.departure.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)

    # Checkpoints for every route
    route_cps: list[list[dict]] = []
    for tl in timelines:
        cps = []
        for idx, mile in enumerate(checkpoint_miles(tl.total_mi, req.interval_mi)):
            lat, lon = geo.interpolate_along(tl.coords, tl.cum_mi, mile)
            cps.append({"index": idx, "mile": mile, "lat": lat, "lon": lon, "eta_ts": dep_ts + tl.clock_at(mile)})
        route_cps.append(cps)

    # One batched weather request covering checkpoints + heatmap corridor
    heat_pts, heat_spacing = corridor_points(timelines)
    cp_keys = sorted({_weather_key((c["lat"], c["lon"])) for cps in route_cps for c in cps})
    all_pts = cp_keys + heat_pts
    last_eta = max(c["eta_ts"] for cps in route_cps for c in cps)
    end = max(dep_hour + timedelta(hours=HEATMAP_HOURS), datetime.fromtimestamp(last_eta, timezone.utc) + timedelta(hours=1))
    horizon = datetime.now(timezone.utc) + timedelta(days=15)
    end = min(end, horizon)
    series = get_weather().hourly(all_pts, dep_hour, end)
    by_key = dict(zip(cp_keys, series[: len(cp_keys)]))
    heat_series = series[len(cp_keys) :]

    routes = []
    for i, (raw, tl, cps) in enumerate(zip(raw_routes, timelines, route_cps)):
        for c in cps:
            wx = sample_series(by_key[_weather_key((c["lat"], c["lon"]))], c["eta_ts"])
            c["weather"] = wx
            if wx is None:
                c["risk"] = None
            else:
                c["risk"] = risk.assess(wx["wind_mph"], wx["rain_in_hr"], wx["snow_in_hr"], req.load_lb).as_dict()
        routes.append(_route_payload(i, raw, tl, cps, req))

    recommended, reason = recommend(routes)
    for r in routes:
        r["recommended"] = r["id"] == recommended["id"]

    return {
        "request": {
            "origin": {"lat": req.origin[0], "lon": req.origin[1], "label": req.origin_label},
            "destination": {"lat": req.destination[0], "lon": req.destination[1], "label": req.destination_label},
            "departure": req.departure.isoformat(),
            "load_lb": req.load_lb,
            "interval_mi": req.interval_mi,
            "apply_hos": req.apply_hos,
        },
        "routes": routes,
        "recommended_id": recommended["id"],
        "recommendation": reason,
        "heatmap": {**_heatmap_payload(heat_pts, heat_series, dep_hour, req.load_lb), "spacing_mi": round(heat_spacing, 1)},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(round(ts), timezone.utc).isoformat().replace("+00:00", "Z")


def _route_payload(i: int, raw: RawRoute, tl: Timeline, cps: list[dict], req: TripRequest) -> dict:
    dep_ts = req.departure.timestamp()
    miles_by_level = {name: 0.0 for name in risk.LEVEL_NAMES}
    unknown_mi = 0.0
    weighted = 0.0
    scored_mi = 0.0
    segments = []
    # Each checkpoint represents the stretch of road closest to it (half-way to its neighbours).
    for j, c in enumerate(cps):
        start = 0.0 if j == 0 else (cps[j - 1]["mile"] + c["mile"]) / 2
        end = tl.total_mi if j == len(cps) - 1 else (c["mile"] + cps[j + 1]["mile"]) / 2
        span = max(0.0, end - start)
        c["span_mi"] = [round(start, 2), round(end, 2)]
        if c["risk"] is None:
            unknown_mi += span
            level = None
        else:
            level = c["risk"]["level"]
            miles_by_level[level] += span
            weighted += c["risk"]["score"] * span
            scored_mi += span
        if span > 0:
            path = geo.simplify(geo.path_between(tl.coords, tl.cum_mi, start, end), 0.03)
            segments.append({"level": level, "path": [[round(a, 5), round(b, 5)] for a, b in path]})

    avg = weighted / scored_mi if scored_mi else None
    max_score = max((c["risk"]["score"] for c in cps if c["risk"]), default=None)

    for c in cps:
        c["mile"] = round(c["mile"], 1)
        c["lat"] = round(c["lat"], 5)
        c["lon"] = round(c["lon"], 5)
        c["eta"] = _iso(c.pop("eta_ts"))

    # Timeline for the map's "truck position" marker: (seconds after departure, lat, lon)
    track = []
    step = max(1.0, tl.total_mi / 400)
    m = 0.0
    while m < tl.total_mi:
        lat, lon = geo.interpolate_along(tl.coords, tl.cum_mi, m)
        track.append([round(tl.clock_at(m)), round(lat, 5), round(lon, 5)])
        m += step
    stops_out = []
    for s in tl.stops:
        mile = tl.mile_at_drive(s.drive_s)
        lat, lon = geo.interpolate_along(tl.coords, tl.cum_mi, mile)
        t0 = clock_seconds(s.drive_s, tl.stops)
        track.append([round(t0), round(lat, 5), round(lon, 5)])
        track.append([round(t0 + s.duration_s), round(lat, 5), round(lon, 5)])
        stops_out.append({
            "kind": s.kind,
            "mile": round(mile, 1),
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "start": _iso(dep_ts + t0),
            "duration_min": round(s.duration_s / 60),
        })
    end_lat, end_lon = tl.coords[-1]
    track.append([round(tl.travel_s), round(end_lat, 5), round(end_lon, 5)])
    track.sort(key=lambda r: r[0])

    letter = ROUTE_LETTERS[i] if i < len(ROUTE_LETTERS) else str(i + 1)
    return {
        "id": letter,
        "name": f"Route {letter}",
        "via": raw.summary or "",
        "distance_mi": round(tl.total_mi, 1),
        "drive_time_s": round(tl.drive_s),
        "travel_time_s": round(tl.travel_s),
        "departure": _iso(dep_ts),
        "arrival": _iso(dep_ts + tl.travel_s),
        "stats": {
            "miles_by_level": {k: round(v, 1) for k, v in miles_by_level.items()},
            "unknown_mi": round(unknown_mi, 1),
            "avg_risk": None if avg is None else round(avg, 3),
            "max_level": None if max_score is None else risk.LEVEL_NAMES[max_score],
        },
        "geometry": [[round(a, 5), round(b, 5)] for a, b in geo.simplify(tl.coords, 0.02)],
        "segments": segments,
        "checkpoints": cps,
        "stops": stops_out,
        "track": track,
    }


# --------------------------------------------------------------------------- recommendation

CRITERIA = (
    ("No Travel miles", lambda r: r["stats"]["miles_by_level"]["No Travel"], "mi"),
    ("Severe miles", lambda r: r["stats"]["miles_by_level"]["Severe"], "mi"),
    ("High miles", lambda r: r["stats"]["miles_by_level"]["High"], "mi"),
    ("average risk", lambda r: r["stats"]["avg_risk"] if r["stats"]["avg_risk"] is not None else 99, ""),
    ("travel time", lambda r: r["travel_time_s"], "s"),
)


def rank_key(r: dict) -> tuple:
    return tuple(round(fn(r), 3) for _, fn, _ in CRITERIA)


def recommend(routes: list[dict]) -> tuple[dict, dict]:
    """Lexicographic ranking per the brief: fewest Severe miles, then fewest High miles,
    then lowest average risk, then shortest travel time. Miles in No Travel conditions are
    checked first (a No Travel mile is strictly worse than a Severe one)."""
    ordered = sorted(routes, key=rank_key)
    for pos, r in enumerate(ordered, 1):
        r["rank"] = pos
    best = ordered[0]
    explanation = {"text": "Only one route option was available.", "deciding_factor": None}
    if len(ordered) > 1:
        runner = ordered[1]
        for label, fn, unit in CRITERIA:
            a, b = round(fn(best), 3), round(fn(runner), 3)
            if a != b:
                lead = "lower" if label == "average risk" else ("shorter" if label == "travel time" else "fewer")
                text = (
                    f"{best['name']} is recommended — {lead} {label}: "
                    f"{_fmt(a, unit)} vs {_fmt(b, unit)} on {runner['name']}."
                )
                if label == "travel time":
                    text += " Weather risk is tied, so the faster route wins."
                explanation = {"deciding_factor": label, "text": text}
                break
        else:
            explanation = {"deciding_factor": None, "text": f"{best['name']} and {runner['name']} are equivalent; picked the first."}
    no_travel = best["stats"]["miles_by_level"]["No Travel"]
    explanation["warning"] = (
        f"Even the best route has {no_travel:.0f} mi in No Travel conditions — consider delaying departure."
        if no_travel > 0
        else None
    )
    return best, explanation


def _fmt(v: float, unit: str) -> str:
    if unit == "s":
        h, m = divmod(int(round(v / 60)), 60)
        return f"{h}h {m:02d}m"
    if unit == "mi":
        return f"{v:.1f} mi"
    return f"{v:.2f}"


# --------------------------------------------------------------------------- heatmap payload


def _heatmap_payload(points: list[geo.LatLon], series: list[HourlySeries], dep_hour: datetime, load_lb: float) -> dict:
    hours = [dep_hour + timedelta(hours=h) for h in range(HEATMAP_HOURS + 1)]
    wind, rain, snow, score = [], [], [], []
    for s in series:
        w_row, r_row, s_row, k_row = [], [], [], []
        for h in hours:
            wx = sample_series(s, h.timestamp())
            if wx is None:
                w_row.append(None); r_row.append(None); s_row.append(None); k_row.append(None)
                continue
            w_row.append(round(wx["wind_mph"], 1))
            r_row.append(round(wx["rain_in_hr"], 3))
            s_row.append(round(wx["snow_in_hr"], 3))
            k_row.append(round(continuous_risk(wx["wind_mph"], wx["rain_in_hr"], wx["snow_in_hr"], load_lb), 2))
        wind.append(w_row); rain.append(r_row); snow.append(s_row); score.append(k_row)
    return {
        "start": hours[0].isoformat().replace("+00:00", "Z"),
        "hours": HEATMAP_HOURS,
        "points": [[round(a, 4), round(b, 4)] for a, b in points],
        "wind_mph": wind,
        "rain_in_hr": rain,
        "snow_in_hr": snow,
        "risk": score,
    }


def continuous_risk(wind: float, rain: float, snow: float, load_lb: float) -> float:
    """Smooth 0-4 risk value for the heatmap. Equals the discrete level at each band's
    lower threshold and rises linearly toward the next, so colours blend instead of
    stepping. The discrete level (which drives all decisions) is never exceeded by more
    than one band fraction."""
    discrete = risk.assess(wind, rain, snow, load_lb).level

    def ramp(v: float, edges: tuple[float, ...]) -> float:
        # edges: thresholds for Moderate, High, Severe, No Travel
        if v < edges[0]:
            return v / edges[0] * 0.99
        for k in range(len(edges) - 1):
            if v < edges[k + 1]:
                return k + 1 + (v - edges[k]) / (edges[k + 1] - edges[k]) * 0.99
        return 4.0

    smooth = max(ramp(wind, (25, 35, 45, 55)), ramp(rain, (0.10, 0.25, 0.50, 1.00)), ramp(snow, (0.5, 1.0, 2.0, 3.0)))
    return min(4.0, max(smooth, float(discrete)))
