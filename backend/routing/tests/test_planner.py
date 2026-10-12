from datetime import datetime, timedelta, timezone

import pytest

from routing.services import geo, planner, providers
from routing.services.planner import HOUR, Stop, TripRequest


def test_polyline_roundtrip():
    pts = [(41.8781, -87.6298), (40.1, -88.9), (38.627, -90.1994)]
    out = geo.decode_polyline(geo.encode_polyline(pts))
    assert all(abs(a - c) < 1e-6 and abs(b - d) < 1e-6 for (a, b), (c, d) in zip(pts, out))


def test_known_google_polyline_precision5():
    # Example from Google's polyline docs
    pts = geo.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@", precision=5)
    assert pts == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


def test_haversine_chicago_stlouis():
    assert 255 < geo.haversine_mi((41.8781, -87.6298), (38.6270, -90.1994)) < 265


def test_checkpoint_miles_include_both_ends():
    assert planner.checkpoint_miles(60, 25) == [0, 25, 50, 60]
    assert planner.checkpoint_miles(50.3, 25) == [0, 25, 50.3]  # last mark within 0.5 mi is merged
    assert planner.checkpoint_miles(8, 10) == [0, 8]


def test_hos_stops():
    assert planner.hos_stops(7 * HOUR, True) == []
    stops = planner.hos_stops(25 * HOUR, True)
    assert [(s.drive_s / HOUR, s.kind) for s in stops] == [(8, "break"), (11, "rest"), (19, "break"), (22, "rest")]
    assert planner.hos_stops(25 * HOUR, False) == []


def test_clock_seconds_adds_stops_before_point():
    stops = [Stop(8 * HOUR, 0.5 * HOUR, "break"), Stop(11 * HOUR, 10 * HOUR, "rest")]
    assert planner.clock_seconds(8 * HOUR, stops) == 8 * HOUR  # arrives, then rests
    assert planner.clock_seconds(9 * HOUR, stops) == 9.5 * HOUR
    assert planner.clock_seconds(12 * HOUR, stops) == 22.5 * HOUR


def test_truck_speed_cap(settings):
    settings.TRUCK_MAX_MPH = 60
    coords = [(40.0, -100.0), (40.0, -99.0)]  # ~53 miles
    raw = providers.RawRoute(coords, [1800.0], 85000, 1800, "")  # OSRM says 30 min (~106 mph)
    tl = planner.build_timeline(raw, apply_hos=False)
    assert tl.drive_s == pytest.approx(tl.total_mi / 60 * HOUR)


def _route(rid, nt=0, sev=0, high=0, avg=0.0, t=3600):
    return {
        "id": rid,
        "name": f"Route {rid}",
        "travel_time_s": t,
        "stats": {"miles_by_level": {"No Travel": nt, "Severe": sev, "High": high}, "avg_risk": avg},
    }


def test_recommendation_order():
    # Severe miles dominate everything below them
    best, why = planner.recommend([_route("A", sev=10, t=100), _route("B", sev=0, high=200, avg=2, t=999)])
    assert best["id"] == "B" and why["deciding_factor"] == "Severe miles"
    # then High miles
    best, _ = planner.recommend([_route("A", high=5), _route("B", high=1, avg=3)])
    assert best["id"] == "B"
    # then average risk
    best, _ = planner.recommend([_route("A", avg=0.5, t=10), _route("B", avg=0.2, t=999)])
    assert best["id"] == "B"
    # then travel time
    best, why = planner.recommend([_route("A", t=5000), _route("B", t=4000)])
    assert best["id"] == "B" and why["deciding_factor"] == "travel time"
    # No Travel miles are worse than Severe miles
    best, why = planner.recommend([_route("A", nt=5), _route("B", sev=50)])
    assert best["id"] == "B" and why["deciding_factor"] == "No Travel miles"


def test_plan_trip_end_to_end_offline():
    dep = datetime.now(timezone.utc) + timedelta(minutes=10)
    req = TripRequest(origin=(41.8781, -87.6298), destination=(39.7392, -104.9903), departure=dep, load_lb=42_000, interval_mi=25)
    out = planner.plan_trip(req)
    routes = out["routes"]
    assert len(routes) == 3
    assert sum(r["recommended"] for r in routes) == 1
    assert out["recommended_id"] == min(routes, key=planner.rank_key)["id"]
    for r in routes:
        cps = r["checkpoints"]
        assert cps[0]["mile"] == 0 and cps[-1]["mile"] == pytest.approx(r["distance_mi"], abs=0.1)
        assert all(b["mile"] - a["mile"] <= 25.01 for a, b in zip(cps, cps[1:]))
        etas = [c["eta"] for c in cps]
        assert etas == sorted(etas)
        # miles per level add up to route length
        assert sum(r["stats"]["miles_by_level"].values()) + r["stats"]["unknown_mi"] == pytest.approx(r["distance_mi"], abs=0.5)
        # ~920 mi at <=65 mph needs a 30-min break and a 10-h rest
        assert {s["kind"] for s in r["stops"]} == {"break", "rest"}
        assert r["travel_time_s"] > r["drive_time_s"] + 10 * 3600
    hm = out["heatmap"]
    assert hm["hours"] == 48 and len(hm["risk"]) == len(hm["points"]) and len(hm["risk"][0]) == 49


def test_eta_drives_weather_sample():
    """Weather is sampled at the checkpoint's ETA, not at departure time."""
    s = providers.HourlySeries(times=[0, 3600, 7200], wind=[10, 30, 50], gust=[0, 0, 0], rain=[0, 0, 0], snow=[0, 0, 0])
    assert planner.sample_series(s, 1800)["wind_mph"] == 20
    assert planner.sample_series(s, 7200)["wind_mph"] == 50
    assert planner.sample_series(s, 7200 + 2 * 3600) is None  # beyond forecast


def test_continuous_risk_matches_levels():
    assert planner.continuous_risk(0, 0, 0, 0) == 0
    assert planner.continuous_risk(35, 0, 0, 0) == pytest.approx(2.0)
    assert planner.continuous_risk(60, 0, 0, 0) == 4.0
    assert planner.continuous_risk(46, 0, 0, 35_000) == 4.0  # load rule


def test_via_points_top_up_to_three_routes(monkeypatch):
    """When the router returns fewer than 3 alternatives, detours via offset points are added."""
    fake = providers.FakeRouter()
    calls = []

    class OneRouteRouter:
        def route(self, waypoints, alternatives=0):
            calls.append(len(waypoints))
            return fake.route(waypoints, alternatives=0)  # only ever one route

    monkeypatch.setattr(planner, "get_router", lambda: OneRouteRouter())
    routes = planner.find_route_options((41.8781, -87.6298), (38.627, -90.1994))
    assert len(routes) == 3
    assert calls[0] == 2 and all(n == 3 for n in calls[1:])  # later calls go through a via point


def test_duplicate_alternatives_are_dropped(monkeypatch):
    fake = providers.FakeRouter()

    class DupRouter:
        def route(self, waypoints, alternatives=0):
            r = fake.route(waypoints, alternatives=0)
            return r * 3 if alternatives else r

    monkeypatch.setattr(planner, "get_router", lambda: DupRouter())
    routes = planner.find_route_options((41.8781, -87.6298), (38.627, -90.1994))
    for i, a in enumerate(routes):
        for b in routes[i + 1 :]:
            assert geo.overlap_fraction(a.coords, b.coords) < 0.9
