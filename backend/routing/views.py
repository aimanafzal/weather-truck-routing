"""JSON API + SPA entry point."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .services.planner import TripRequest, plan_trip
from .services.providers import ProviderError, get_geocoder

log = logging.getLogger(__name__)

ALLOWED_INTERVALS = (10, 25, 50)
COORD_RE = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


class BadRequest(Exception):
    pass


def _error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


@require_GET
def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "provider_mode": settings.PROVIDER_MODE})


@require_GET
def geocode(request: HttpRequest) -> JsonResponse:
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})
    if m := COORD_RE.match(q):
        lat, lon = float(m.group(1)), float(m.group(2))
        return JsonResponse({"results": [{"label": f"{lat:.4f}, {lon:.4f}", "lat": lat, "lon": lon}]})
    try:
        return JsonResponse({"results": get_geocoder().search(q[:120])})
    except ProviderError as exc:
        return _error(str(exc), 502)


@csrf_exempt  # stateless JSON API, no cookies/sessions are used
@require_POST
def plan(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body or b"{}")
        trip = _parse_trip(body)
    except (ValueError, BadRequest) as exc:
        return _error(str(exc))
    try:
        return JsonResponse(plan_trip(trip))
    except ProviderError as exc:
        log.warning("provider error: %s", exc)
        return _error(str(exc), 502)


def _parse_place(value, field: str) -> tuple[tuple[float, float], str]:
    if isinstance(value, dict) and "lat" in value and "lon" in value:
        lat, lon = float(value["lat"]), float(value["lon"])
        label = str(value.get("label") or f"{lat:.4f}, {lon:.4f}")
    elif isinstance(value, str) and value.strip():
        if m := COORD_RE.match(value):
            lat, lon = float(m.group(1)), float(m.group(2))
            label = value.strip()
        else:
            try:
                hits = get_geocoder().search(value.strip(), limit=1)
            except ProviderError as exc:
                raise BadRequest(f"Could not look up {field}: {exc}")
            if not hits:
                raise BadRequest(f"Could not find a location matching '{value}'.")
            lat, lon, label = hits[0]["lat"], hits[0]["lon"], hits[0]["label"]
    else:
        raise BadRequest(f"{field.capitalize()} is required.")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise BadRequest(f"{field.capitalize()} coordinates are out of range.")
    return (lat, lon), label


def _parse_trip(body: dict) -> TripRequest:
    if not isinstance(body, dict):
        raise BadRequest("Request body must be a JSON object.")
    origin, origin_label = _parse_place(body.get("origin"), "origin")
    dest, dest_label = _parse_place(body.get("destination"), "destination")
    if abs(origin[0] - dest[0]) < 1e-4 and abs(origin[1] - dest[1]) < 1e-4:
        raise BadRequest("Origin and destination are the same place.")

    raw_dep = body.get("departure")
    if not raw_dep:
        departure = datetime.now(timezone.utc)
    else:
        try:
            departure = datetime.fromisoformat(str(raw_dep).replace("Z", "+00:00"))
        except ValueError:
            raise BadRequest("Departure must be an ISO-8601 date/time.")
        if departure.tzinfo is None:
            raise BadRequest("Departure must include a timezone offset (e.g. 2026-10-12T08:00:00-05:00).")
    now = datetime.now(timezone.utc)
    if departure < now - timedelta(hours=1):
        raise BadRequest("Departure is in the past — forecasts are only available from now onwards.")
    if departure > now + timedelta(days=7):
        raise BadRequest("Departure must be within the next 7 days (forecast range).")

    try:
        load = float(body.get("load_weight_lb"))
    except (TypeError, ValueError):
        raise BadRequest("Load weight (lb) is required and must be a number.")
    if not 0 <= load <= settings.MAX_LOAD_LB:
        raise BadRequest(f"Load weight must be between 0 and {settings.MAX_LOAD_LB:,} lb.")

    try:
        interval = int(body.get("interval_mi", 25))
    except (TypeError, ValueError):
        raise BadRequest("Checkpoint interval must be 10, 25 or 50 miles.")
    if interval not in ALLOWED_INTERVALS:
        raise BadRequest("Checkpoint interval must be 10, 25 or 50 miles.")

    return TripRequest(
        origin=origin,
        destination=dest,
        departure=departure,
        load_lb=load,
        interval_mi=interval,
        apply_hos=bool(body.get("apply_hos", True)),
        origin_label=origin_label,
        destination_label=dest_label,
    )


def spa(request: HttpRequest) -> HttpResponse:
    index = settings.FRONTEND_DIST / "index.html"
    if not index.exists():
        return HttpResponse(
            "<h1>Frontend not built</h1><p>Run <code>npm run build</code> in <code>frontend/</code>, "
            "or use the Vite dev server on port 5173.</p>",
            status=503,
        )
    resp = HttpResponse(index.read_bytes(), content_type="text/html; charset=utf-8")
    resp["Cache-Control"] = "no-cache"
    return resp
