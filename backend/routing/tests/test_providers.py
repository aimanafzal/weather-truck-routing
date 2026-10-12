"""Parsers for the live APIs, fed with payloads shaped exactly like the real responses."""
from datetime import datetime, timezone

from routing.services import geo, providers


def test_osrm_parse(monkeypatch, settings):
    coords = [(41.8781, -87.6298), (41.0, -88.5), (40.0, -89.0), (38.627, -90.1994)]
    payload = {
        "code": "Ok",
        "routes": [
            {
                "geometry": geo.encode_polyline(coords, 6),
                "distance": 477336.9,
                "duration": 20210.9,
                "weight_name": "routability",
                "weight": 20210.9,
                "legs": [
                    {
                        "summary": "I 55, Barack Obama Presidential Expressway",
                        "distance": 477336.9,
                        "duration": 20210.9,
                        "annotation": {"duration": [6000.0, 7000.0, 7210.9]},
                        "steps": [],
                    }
                ],
            }
        ],
        "waypoints": [],
    }
    seen = {}

    def fake_get(url, params=None, timeout=20):
        seen["url"], seen["params"] = url, params
        return payload

    monkeypatch.setattr(providers, "_get_json", fake_get)
    routes = providers.OsrmRouter("https://router.example").route([coords[0], coords[-1]], alternatives=3)
    assert seen["url"].startswith("https://router.example/route/v1/driving/-87.629800,41.878100;")
    assert seen["params"]["geometries"] == "polyline6" and seen["params"]["alternatives"] == "3"
    r = routes[0]
    assert len(r.coords) == 4 and r.seg_seconds == [6000.0, 7000.0, 7210.9]
    assert r.summary == "I 55, Barack Obama Presidential Expressway"


def test_osrm_error(monkeypatch):
    monkeypatch.setattr(providers, "_get_json", lambda *a, **k: {"code": "NoRoute", "message": "Impossible route"})
    try:
        providers.OsrmRouter("https://x").route([(0, 0), (1, 1)])
    except providers.ProviderError as exc:
        assert "NoRoute" in str(exc)
    else:
        raise AssertionError("expected ProviderError")


def test_open_meteo_parse_multi_location(monkeypatch):
    item = lambda lat: {  # noqa: E731
        "latitude": lat,
        "longitude": -87.6,
        "hourly_units": {"time": "iso8601", "wind_speed_10m": "mp/h", "rain": "inch", "snowfall": "inch"},
        "hourly": {
            "time": ["2026-10-12T14:00", "2026-10-12T15:00"],
            "wind_speed_10m": [8.3, 8.5],
            "wind_gusts_10m": [12.0, None],
            "rain": [0.1, 0.0],
            "showers": [0.05, 0.0],
            "snowfall": [0.0, 0.2],
        },
    }
    monkeypatch.setattr(providers, "_get_json", lambda url, params=None, timeout=20: [item(41.8), item(40.0)])
    start = datetime(2026, 10, 12, 14, tzinfo=timezone.utc)
    out = providers.OpenMeteoWeather("https://w").hourly([(41.8, -87.6), (40.0, -88.0)], start, start)
    assert len(out) == 2
    s = out[0]
    assert s.times[0] == start.timestamp()
    assert s.rain == [0.15000000000000002, 0.0] or abs(s.rain[0] - 0.15) < 1e-9
    assert s.gust == [12.0, 0.0] and s.snow == [0.0, 0.2]


def test_open_meteo_single_location_object(monkeypatch):
    single = {"hourly": {"time": ["2026-10-12T14:00"], "wind_speed_10m": [5], "wind_gusts_10m": [7], "rain": [0], "showers": [0], "snowfall": [0]}}
    monkeypatch.setattr(providers, "_get_json", lambda *a, **k: single)
    start = datetime(2026, 10, 12, 14, tzinfo=timezone.utc)
    out = providers.OpenMeteoWeather("https://w").hourly([(1.0, 2.0)], start, start)
    assert out[0].wind == [5.0]


def test_photon_parse(monkeypatch):
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Denver", "state": "Colorado", "country": "United States", "countrycode": "US"},
                "geometry": {"type": "Point", "coordinates": [-104.984862, 39.7392364]},
            }
        ],
    }
    monkeypatch.setattr(providers, "_get_json", lambda *a, **k: payload)
    res = providers.PhotonGeocoder("https://p").search("Denver")
    assert res == [{"label": "Denver, Colorado, US", "lat": 39.7392364, "lon": -104.984862}]
