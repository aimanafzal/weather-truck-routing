"""Third-party data providers: routing (OSRM), weather (Open-Meteo), geocoding (Photon).

All three are free, key-less public APIs. Each has an offline "fake" twin used by the
test suite and for demos without internet (set PROVIDER_MODE=fake).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
from django.conf import settings
from django.core.cache import cache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import geo

log = logging.getLogger(__name__)


class ProviderError(Exception):
    """Raised when an upstream API fails or returns something unusable."""


def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=8))
    s.headers["User-Agent"] = settings.HTTP_USER_AGENT
    return s


_SESSION: requests.Session | None = None


def http() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = _session()
    return _SESSION


def _get_json(url: str, params: dict | None = None, timeout: float = 20) -> dict | list:
    try:
        resp = http().get(url, params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise ProviderError(f"Could not reach {url.split('/')[2]}: {exc.__class__.__name__}") from exc
    if resp.status_code >= 400:
        raise ProviderError(f"{url.split('/')[2]} returned HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise ProviderError(f"{url.split('/')[2]} returned invalid JSON") from exc


# --------------------------------------------------------------------------- routing


@dataclass
class RawRoute:
    coords: list[geo.LatLon]
    seg_seconds: list[float]  # per-segment duration (len = len(coords) - 1)
    distance_m: float
    duration_s: float
    summary: str


class OsrmRouter:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def route(self, waypoints: list[geo.LatLon], alternatives: int = 0) -> list[RawRoute]:
        path = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in waypoints)
        params = {
            "overview": "full",
            "geometries": "polyline6",
            "steps": "true",  # needed for leg summaries (road names)
            "annotations": "duration",
            "alternatives": str(alternatives) if alternatives else "false",
        }
        key = "osrm:" + hashlib.sha1(json.dumps([path, params]).encode()).hexdigest()
        data = cache.get(key)
        if data is None:
            data = _get_json(f"{self.base}/route/v1/driving/{path}", params, timeout=30)
            if data.get("code") == "Ok":
                cache.set(key, data, 60 * 60)
        if data.get("code") != "Ok":
            raise ProviderError(f"Routing failed: {data.get('code')} {data.get('message', '')}".strip())
        return [self._parse(r) for r in data.get("routes", [])]

    @staticmethod
    def _parse(r: dict) -> RawRoute:
        coords = geo.decode_polyline(r["geometry"], 6)
        seg: list[float] = []
        for leg in r.get("legs", []):
            seg.extend(leg.get("annotation", {}).get("duration", []))
        if len(seg) != len(coords) - 1:
            # Fall back to spreading the total duration proportionally to distance.
            cum = geo.cumulative_miles(coords)
            total = cum[-1] or 1
            seg = [(cum[i + 1] - cum[i]) / total * r["duration"] for i in range(len(coords) - 1)]
        names: list[str] = []
        for leg in r.get("legs", []):
            for part in (leg.get("summary") or "").split(","):
                part = part.strip()
                if part and part not in names:
                    names.append(part)
        return RawRoute(coords, seg, r["distance"], r["duration"], ", ".join(names[:3]))


class FakeRouter:
    """Deterministic offline router: gently curved paths, ~55 mph average."""

    def route(self, waypoints: list[geo.LatLon], alternatives: int = 0) -> list[RawRoute]:
        bends = [0.0] + ([0.06, -0.09] if alternatives else [])
        return [self._make(waypoints, b) for b in bends]

    @staticmethod
    def _make(waypoints: list[geo.LatLon], bend: float) -> RawRoute:
        coords: list[geo.LatLon] = []
        for a, b in zip(waypoints, waypoints[1:]):
            dist = geo.haversine_mi(a, b)
            brg = geo.bearing_deg(a, b)
            n = max(8, int(dist / 2))
            for i in range(n + (1 if b == waypoints[-1] else 0)):
                t = i / n
                p = geo.destination(a, brg, dist * t)
                off = math.sin(math.pi * t) * dist * bend
                coords.append(geo.destination(p, brg + 90, off) if off else p)
        cum = geo.cumulative_miles(coords)
        seg = [(cum[i + 1] - cum[i]) / 55 * 3600 for i in range(len(coords) - 1)]
        return RawRoute(coords, seg, cum[-1] * geo.METERS_PER_MILE, sum(seg), f"Fake Hwy {int(abs(bend) * 100)}")


# --------------------------------------------------------------------------- weather

HOURLY_VARS = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"


@dataclass
class HourlySeries:
    """Hourly weather for one location. times are UTC epoch seconds."""

    times: list[float]
    wind: list[float]  # mph, sustained 10 m
    gust: list[float]  # mph
    rain: list[float]  # in/hr, liquid (rain + showers)
    snow: list[float]  # in/hr, snowfall


def _hour_str(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00")


class OpenMeteoWeather:
    BATCH = 50

    def __init__(self, base_url: str, api_key: str = ""):
        self.base = base_url.rstrip("/")
        self.api_key = api_key

    def hourly(self, points: list[geo.LatLon], start: datetime, end: datetime) -> list[HourlySeries]:
        out: list[HourlySeries | None] = [None] * len(points)
        todo: list[int] = []
        window = (_hour_str(start), _hour_str(end))
        for i, p in enumerate(points):
            hit = cache.get(self._key(p, window))
            if hit is not None:
                out[i] = hit
            else:
                todo.append(i)
        for chunk_start in range(0, len(todo), self.BATCH):
            idx = todo[chunk_start : chunk_start + self.BATCH]
            params = {
                "latitude": ",".join(f"{points[i][0]:.4f}" for i in idx),
                "longitude": ",".join(f"{points[i][1]:.4f}" for i in idx),
                "hourly": HOURLY_VARS,
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
                "timezone": "UTC",
                "start_hour": window[0],
                "end_hour": window[1],
            }
            if self.api_key:
                params["apikey"] = self.api_key
            data = _get_json(f"{self.base}/v1/forecast", params, timeout=30)
            if isinstance(data, dict):
                if data.get("error"):
                    raise ProviderError(f"Weather API error: {data.get('reason')}")
                data = [data]
            if len(data) != len(idx):
                raise ProviderError("Weather API returned an unexpected number of locations")
            for i, item in zip(idx, data):
                series = self._parse(item)
                cache.set(self._key(points[i], window), series, 30 * 60)
                out[i] = series
        return out  # type: ignore[return-value]

    @staticmethod
    def _key(p: geo.LatLon, window: tuple[str, str]) -> str:
        return f"om:{p[0]:.4f}:{p[1]:.4f}:{window[0]}:{window[1]}"

    @staticmethod
    def _parse(item: dict) -> HourlySeries:
        h = item["hourly"]

        def nums(key: str) -> list[float]:
            return [float(v) if v is not None else 0.0 for v in h.get(key, [0.0] * len(h["time"]))]

        times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc).timestamp() for t in h["time"]]
        rain = [a + b for a, b in zip(nums("rain"), nums("showers"))]
        return HourlySeries(times, nums("wind_speed_10m"), nums("wind_gusts_10m"), rain, nums("snowfall"))


class FakeWeather:
    """Deterministic synthetic weather: a storm cell drifting east across the Midwest."""

    STORM_START = (39.0, -97.0)  # lat, lon at t0
    DRIFT_DEG_PER_HOUR = 0.35  # eastward

    def hourly(self, points: list[geo.LatLon], start: datetime, end: datetime) -> list[HourlySeries]:
        t0 = start.replace(minute=0, second=0, microsecond=0)
        hours = int((end - t0).total_seconds() // 3600) + 1
        times = [(t0 + timedelta(hours=h)).timestamp() for h in range(hours)]
        result = []
        for lat, lon in points:
            wind, gust, rain, snow = [], [], [], []
            for h in range(hours):
                c_lat, c_lon = self.STORM_START[0], self.STORM_START[1] + self.DRIFT_DEG_PER_HOUR * h
                d = geo.haversine_mi((lat, lon), (c_lat, c_lon))
                k = math.exp(-((d / 140) ** 2))
                w = 8 + 52 * k
                wind.append(round(w, 1))
                gust.append(round(w * 1.4, 1))
                cold = lat > 41.5
                rain.append(0.0 if cold else round(1.2 * k, 2))
                snow.append(round(3.4 * k, 2) if cold else 0.0)
            result.append(HourlySeries(times, wind, gust, rain, snow))
        return result


# --------------------------------------------------------------------------- geocoding


class PhotonGeocoder:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def search(self, query: str, limit: int = 6) -> list[dict]:
        key = "geo:" + hashlib.sha1(f"{query.lower()}:{limit}".encode()).hexdigest()
        hit = cache.get(key)
        if hit is not None:
            return hit
        params = {"q": query, "limit": limit, "lang": "en"}
        # Bias toward the continental US (trucking use case) without excluding elsewhere.
        params.update({"lat": 39.5, "lon": -98.35})
        data = _get_json(f"{self.base}/api/", params, timeout=10)
        results = []
        for f in data.get("features", []):
            p = f.get("properties", {})
            lon, lat = f["geometry"]["coordinates"]
            parts = [p.get("name"), p.get("city") if p.get("city") != p.get("name") else None, p.get("state"), p.get("countrycode")]
            label = ", ".join(x for x in parts if x)
            results.append({"label": label or query, "lat": lat, "lon": lon})
        cache.set(key, results, 24 * 3600)
        return results


class FakeGeocoder:
    PLACES = {
        "chicago": ("Chicago, Illinois, US", 41.8781, -87.6298),
        "st. louis": ("St. Louis, Missouri, US", 38.6270, -90.1994),
        "st louis": ("St. Louis, Missouri, US", 38.6270, -90.1994),
        "kansas city": ("Kansas City, Missouri, US", 39.0997, -94.5786),
        "denver": ("Denver, Colorado, US", 39.7392, -104.9903),
        "dallas": ("Dallas, Texas, US", 32.7767, -96.7970),
        "omaha": ("Omaha, Nebraska, US", 41.2565, -95.9345),
        "minneapolis": ("Minneapolis, Minnesota, US", 44.9778, -93.2650),
    }

    def search(self, query: str, limit: int = 6) -> list[dict]:
        q = query.lower().strip()
        return [
            {"label": label, "lat": lat, "lon": lon}
            for key, (label, lat, lon) in self.PLACES.items()
            if key.startswith(q) or q in key
        ][:limit]


# --------------------------------------------------------------------------- factory


def get_router():
    return FakeRouter() if settings.PROVIDER_MODE == "fake" else OsrmRouter(settings.OSRM_URL)


def get_weather():
    if settings.PROVIDER_MODE == "fake":
        return FakeWeather()
    return OpenMeteoWeather(settings.OPEN_METEO_URL, settings.OPEN_METEO_API_KEY)


def get_geocoder():
    return FakeGeocoder() if settings.PROVIDER_MODE == "fake" else PhotonGeocoder(settings.PHOTON_URL)
