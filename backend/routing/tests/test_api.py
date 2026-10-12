import json
from datetime import datetime, timedelta, timezone

import pytest


def _post(client, **overrides):
    body = {
        "origin": {"lat": 41.8781, "lon": -87.6298, "label": "Chicago"},
        "destination": "st louis",
        "departure": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "load_weight_lb": 35000,
        "interval_mi": 10,
    }
    body.update(overrides)
    return client.post("/api/plan", json.dumps(body), content_type="application/json")


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_geocode(client):
    res = client.get("/api/geocode", {"q": "denv"}).json()["results"]
    assert res[0]["label"].startswith("Denver")
    assert client.get("/api/geocode", {"q": "39.5, -98.2"}).json()["results"][0]["lat"] == 39.5


def test_plan_ok(client):
    r = _post(client)
    assert r.status_code == 200, r.content
    data = r.json()
    assert len(data["routes"]) == 3
    assert data["request"]["destination"]["label"].startswith("St. Louis")
    assert data["recommendation"]["text"]


@pytest.mark.parametrize(
    "override,msg",
    [
        ({"load_weight_lb": "heavy"}, "Load weight"),
        ({"load_weight_lb": 120000}, "between 0"),
        ({"interval_mi": 15}, "10, 25 or 50"),
        ({"departure": "2020-01-01T00:00:00Z"}, "past"),
        ({"departure": "2026-10-12T08:00:00"}, "timezone"),
        ({"destination": "nowhere-ville-xyz"}, "Could not find"),
        ({"origin": ""}, "Origin is required"),
    ],
)
def test_plan_validation(client, override, msg):
    r = _post(client, **override)
    assert r.status_code == 400
    assert msg in r.json()["error"]


def test_plan_far_future_rejected(client):
    r = _post(client, departure=(datetime.now(timezone.utc) + timedelta(days=9)).isoformat())
    assert r.status_code == 400


def test_spa_fallback(client, settings, tmp_path):
    settings.FRONTEND_DIST = tmp_path
    assert client.get("/some/page").status_code == 503
    (tmp_path / "index.html").write_text("<div id=root></div>")
    r = client.get("/some/page")
    assert r.status_code == 200 and b"root" in r.content
