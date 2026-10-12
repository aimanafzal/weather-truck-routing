"""Small geodesy helpers: distances, polyline decoding, and walking along a path.

Coordinates are (lat, lon) tuples in degrees throughout this module.
"""
from __future__ import annotations

import bisect
import math
from typing import Iterable, Sequence

EARTH_RADIUS_MI = 3958.7613
METERS_PER_MILE = 1609.344

LatLon = tuple[float, float]


def haversine_mi(a: LatLon, b: LatLon) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(h)))


def bearing_deg(a: LatLon, b: LatLon) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def destination(origin: LatLon, bearing: float, distance_mi: float) -> LatLon:
    """Point reached travelling `distance_mi` from `origin` on initial `bearing`."""
    lat1, lon1 = map(math.radians, origin)
    brg = math.radians(bearing)
    d = distance_mi / EARTH_RADIUS_MI
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(brg))
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(d) * math.cos(lat1), math.cos(d) - math.sin(lat1) * math.sin(lat2)
    )
    return (math.degrees(lat2), (math.degrees(lon2) + 540) % 360 - 180)


def midpoint(a: LatLon, b: LatLon) -> LatLon:
    return destination(a, bearing_deg(a, b), haversine_mi(a, b) / 2)


def decode_polyline(encoded: str, precision: int = 6) -> list[LatLon]:
    """Decode a Google-style encoded polyline (OSRM `polyline6` by default)."""
    coords: list[LatLon] = []
    index = lat = lon = 0
    factor = 10 ** precision
    length = len(encoded)
    while index < length:
        for is_lon in (False, True):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if is_lon:
                lon += delta
            else:
                lat += delta
        coords.append((lat / factor, lon / factor))
    return coords


def encode_polyline(coords: Iterable[LatLon], precision: int = 6) -> str:
    """Inverse of decode_polyline (used by the offline provider and tests)."""
    factor = 10 ** precision
    out: list[str] = []
    prev_lat = prev_lon = 0
    for lat, lon in coords:
        ilat, ilon = round(lat * factor), round(lon * factor)
        for delta in (ilat - prev_lat, ilon - prev_lon):
            v = ~(delta << 1) if delta < 0 else delta << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        prev_lat, prev_lon = ilat, ilon
    return "".join(out)


def cumulative_miles(coords: Sequence[LatLon]) -> list[float]:
    cum = [0.0]
    for i in range(1, len(coords)):
        cum.append(cum[-1] + haversine_mi(coords[i - 1], coords[i]))
    return cum


def interpolate_along(coords: Sequence[LatLon], cum: Sequence[float], mile: float) -> LatLon:
    """Position at `mile` along a path whose cumulative mileage is `cum`."""
    if mile <= 0:
        return coords[0]
    if mile >= cum[-1]:
        return coords[-1]
    i = bisect.bisect_right(cum, mile)
    seg = cum[i] - cum[i - 1]
    t = 0.0 if seg == 0 else (mile - cum[i - 1]) / seg
    (lat1, lon1), (lat2, lon2) = coords[i - 1], coords[i]
    return (lat1 + (lat2 - lat1) * t, lon1 + (lon2 - lon1) * t)


def interp_series(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    """Piecewise-linear interpolation of ys over monotonically increasing xs (clamped)."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect.bisect_right(xs, x)
    span = xs[i] - xs[i - 1]
    t = 0.0 if span == 0 else (x - xs[i - 1]) / span
    return ys[i - 1] + (ys[i] - ys[i - 1]) * t


def path_between(coords: Sequence[LatLon], cum: Sequence[float], start_mi: float, end_mi: float) -> list[LatLon]:
    """Sub-path from start_mi to end_mi, including interpolated end points."""
    pts = [interpolate_along(coords, cum, start_mi)]
    lo = bisect.bisect_right(cum, start_mi)
    hi = bisect.bisect_left(cum, end_mi)
    pts.extend(coords[lo:hi])
    pts.append(interpolate_along(coords, cum, end_mi))
    return pts


def simplify(coords: Sequence[LatLon], tolerance_mi: float = 0.05) -> list[LatLon]:
    """Iterative Douglas-Peucker simplification (planar approximation, fine for display)."""
    n = len(coords)
    if n <= 2:
        return list(coords)
    lat0 = math.radians(sum(c[0] for c in coords) / n)
    kx = 69.172 * math.cos(lat0)
    ky = 69.0
    pts = [(c[1] * kx, c[0] * ky) for c in coords]
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        s, e = stack.pop()
        (x1, y1), (x2, y2) = pts[s], pts[e]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        best, best_i = -1.0, -1
        for i in range(s + 1, e):
            px, py = pts[i]
            if norm == 0:
                d = math.hypot(px - x1, py - y1)
            else:
                d = abs(dy * px - dx * py + x2 * y1 - y2 * x1) / norm
            if d > best:
                best, best_i = d, i
        if best > tolerance_mi and best_i > 0:
            keep[best_i] = True
            stack.append((s, best_i))
            stack.append((best_i, e))
    return [c for c, k in zip(coords, keep) if k]


def overlap_fraction(a: Sequence[LatLon], b: Sequence[LatLon], threshold_mi: float = 1.5, samples: int = 60) -> float:
    """Share of path `a` (sampled) that lies within `threshold_mi` of path `b`'s vertices."""
    if not a or not b:
        return 0.0
    cum_a = cumulative_miles(a)
    total = cum_a[-1] or 1.0
    probe = [interpolate_along(a, cum_a, total * i / (samples - 1)) for i in range(samples)]
    cum_b = cumulative_miles(b)
    step = max(0.5, threshold_mi / 2)
    dense_b = [interpolate_along(b, cum_b, m) for m in _frange(0, cum_b[-1], step)] + [b[-1]]
    # bucket b's points on a coarse grid for speed
    cell = 0.1
    grid: dict[tuple[int, int], list[LatLon]] = {}
    for p in dense_b:
        grid.setdefault((int(p[0] // cell), int(p[1] // cell)), []).append(p)
    hits = 0
    for p in probe:
        gx, gy = int(p[0] // cell), int(p[1] // cell)
        near = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for q in grid.get((gx + dx, gy + dy), ()):
                    if haversine_mi(p, q) <= threshold_mi:
                        near = True
                        break
                if near:
                    break
            if near:
                break
        hits += near
    return hits / len(probe)


def _frange(start: float, stop: float, step: float):
    x = start
    while x < stop:
        yield x
        x += step
