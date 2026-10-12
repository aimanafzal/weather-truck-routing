import { useEffect, useMemo, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { CorridorHeatLayer } from "../lib/heatLayer.js";
import { levelColor, METRICS, toRiskScale } from "../lib/risk.js";
import { fmtDuration, fmtMiles, fmtDateTime } from "../lib/format.js";
import { positionAt, valueAt } from "../lib/track.js";

// Esri's light-grey canvas needs no API key and keeps the heatmap readable.
// Override with VITE_TILE_URL / VITE_TILE_ATTRIBUTION at build time to use another provider.
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas";
const TILE_URL = import.meta.env.VITE_TILE_URL || `${ESRI}/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}`;
const LABELS_URL = import.meta.env.VITE_TILE_URL ? null : `${ESRI}/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}`;
const TILE_ATTR =
  import.meta.env.VITE_TILE_ATTRIBUTION ||
  'Basemap &copy; <a href="https://www.esri.com">Esri</a>, HERE, Garmin, &copy; OpenStreetMap contributors | Routing <a href="https://project-osrm.org">OSRM</a> | Weather <a href="https://open-meteo.com">Open-Meteo</a>';

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function checkpointPopup(route, cp) {
  const w = cp.weather;
  const r = cp.risk;
  const level = r?.level ?? "Unknown";
  return `
    <div class="pop">
      <div class="pop-head"><span class="pop-dot" style="background:${levelColor(r?.level)}"></span>
        <strong>${esc(route.name)}, mile ${cp.mile}</strong></div>
      <div class="pop-sub">ETA ${esc(fmtDateTime(cp.eta))}</div>
      <div class="pop-level" style="color:${levelColor(r?.level)}">${esc(level)}</div>
      ${
        w
          ? `<table class="pop-wx">
              <tr><td>Wind</td><td>${w.wind_mph} mph <span class="muted">(gusts ${w.gust_mph})</span></td><td>${esc(r.factors.wind)}</td></tr>
              <tr><td>Rain</td><td>${w.rain_in_hr.toFixed(2)} in/hr</td><td>${esc(r.factors.rain)}</td></tr>
              <tr><td>Snow</td><td>${w.snow_in_hr.toFixed(2)} in/hr</td><td>${esc(r.factors.snow)}</td></tr>
            </table>
            <ul class="pop-reasons">${r.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`
          : `<p class="muted">No forecast available for this time.</p>`
      }
    </div>`;
}

const pinIcon = (label, cls) =>
  L.divIcon({ className: `pin ${cls}`, html: `<span>${label}</span>`, iconSize: [26, 26], iconAnchor: [13, 13] });

export default function MapView({ result, selectedId, onSelect, hour, metric, showHeat }) {
  const el = useRef(null);
  const mapRef = useRef(null);
  const layers = useRef({});

  // ---- create map once
  useEffect(() => {
    const map = L.map(el.current, { zoomControl: false, preferCanvas: true, worldCopyJump: true }).setView([39.5, -96], 4);
    L.control.zoom({ position: "bottomright" }).addTo(map);
    L.tileLayer(TILE_URL, { attribution: TILE_ATTR, maxZoom: 16 }).addTo(map);
    map.createPane("routes").style.zIndex = 420;
    map.createPane("points").style.zIndex = 450;
    if (LABELS_URL) {
      // Place names drawn above the heatmap and routes so they stay legible.
      const labels = map.createPane("labels");
      labels.style.zIndex = 460;
      labels.style.pointerEvents = "none";
      L.tileLayer(LABELS_URL, { pane: "labels", maxZoom: 16 }).addTo(map);
    }
    layers.current.heat = new CorridorHeatLayer({ pane: "overlayPane" });
    mapRef.current = map;
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(el.current);
    return () => {
      ro.disconnect();
      map.remove();
    };
  }, []);

  // ---- routes, checkpoints, stops (rebuild when result or selection changes)
  useEffect(() => {
    const map = mapRef.current;
    const L_ = layers.current;
    L_.routes?.remove();
    L_.endpoints?.remove();
    if (!result) return;
    const group = L.featureGroup();
    const renderer = L.canvas({ pane: "routes", tolerance: 6 });
    const pointRenderer = L.canvas({ pane: "points", tolerance: 4 });
    const ordered = [...result.routes].sort((a, b) => (a.id === selectedId) - (b.id === selectedId)); // selected on top

    for (const route of ordered) {
      const selected = route.id === selectedId;
      const labelAt = [0.5, 0.33, 0.67][result.routes.indexOf(route) % 3]; // stagger labels
      const casing = L.polyline(route.geometry, {
        renderer,
        color: selected ? "#14212A" : "#4F6170",
        weight: selected ? 10 : 7,
        opacity: selected ? 0.9 : 0.55,
        lineCap: "round",
        lineJoin: "round",
      });
      casing.on("click", () => onSelect(route.id));
      group.addLayer(casing);

      if (selected) {
        for (const seg of route.segments) {
          group.addLayer(
            L.polyline(seg.path, { renderer, color: levelColor(seg.level), weight: 6, opacity: 1, lineCap: "round", interactive: false })
          );
        }
      } else {
        group.addLayer(L.polyline(route.geometry, { renderer, color: "#C9D3DA", weight: 3, opacity: 0.9, dashArray: "6 7", interactive: false }));
      }

      // Route summary label at the middle of the line
      const mid = route.geometry[Math.floor((route.geometry.length - 1) * labelAt)];
      const nt = route.stats.miles_by_level["No Travel"];
      const sev = route.stats.miles_by_level.Severe;
      const label = `<b>${esc(route.name)}${route.recommended ? " (best)" : ""}</b><br>${fmtMiles(route.distance_mi)}, ${fmtDuration(route.travel_time_s)}<br>${
        nt > 0 ? `${Math.round(nt)} mi No Travel` : sev > 0 ? `${Math.round(sev)} mi Severe` : `Worst: ${route.stats.max_level ?? "n/a"}`
      }`;
      group.addLayer(
        L.marker(mid, { icon: L.divIcon({ className: "", html: "", iconSize: [0, 0] }), interactive: false, keyboard: false }).bindTooltip(label, {
          permanent: true,
          direction: "center",
          className: `route-label${selected ? " is-selected" : ""}${route.recommended ? " is-best" : ""}`,
        })
      );

      for (const cp of route.checkpoints) {
        const m = L.circleMarker([cp.lat, cp.lon], {
          renderer: pointRenderer,
          radius: selected ? 6 : 3.5,
          color: selected ? "#fff" : "#14212A",
          weight: selected ? 2 : 1,
          fillColor: levelColor(cp.risk?.level),
          fillOpacity: selected ? 1 : 0.8,
        });
        m.bindPopup(() => checkpointPopup(route, cp), { maxWidth: 300, className: "cp-popup" });
        m.on("click", () => onSelect(route.id));
        group.addLayer(m);
      }

      if (selected) {
        for (const s of route.stops) {
          group.addLayer(
            L.marker([s.lat, s.lon], { icon: pinIcon(s.kind === "rest" ? "Z" : "B", "pin-stop"), zIndexOffset: 500 }).bindPopup(
              `<div class="pop"><strong>${s.kind === "rest" ? "10-hour rest" : "30-minute break"}</strong><div class="pop-sub">Mile ${s.mile}, from ${esc(
                fmtDateTime(s.start)
              )}</div><p class="muted">Hours-of-service stop, included in ETAs.</p></div>`
            )
          );
        }
      }
    }
    group.addTo(map);
    L_.routes = group;

    const { origin, destination } = result.request;
    L_.endpoints = L.layerGroup([
      L.marker([origin.lat, origin.lon], { icon: pinIcon("A", "pin-origin"), zIndexOffset: 1000 }).bindTooltip(esc(origin.label)),
      L.marker([destination.lat, destination.lon], { icon: pinIcon("B", "pin-dest"), zIndexOffset: 1000 }).bindTooltip(esc(destination.label)),
    ]).addTo(map);
  }, [result, selectedId, onSelect]);

  // ---- fit bounds only when a new result arrives
  useEffect(() => {
    if (!result) return;
    const b = L.latLngBounds(result.routes.flatMap((r) => [r.geometry[0], ...r.geometry.filter((_, i) => i % 20 === 0), r.geometry.at(-1)]));
    mapRef.current.fitBounds(b, { padding: [40, 40], maxZoom: 9 });
  }, [result]);

  // ---- heatmap points
  const heat = result?.heatmap;
  useEffect(() => {
    const map = mapRef.current;
    const layer = layers.current.heat;
    if (!heat || !showHeat) {
      if (map.hasLayer(layer)) map.removeLayer(layer);
      return;
    }
    if (!map.hasLayer(layer)) layer.addTo(map);
    layer.setPoints(heat.points, heat.spacing_mi);
  }, [heat, showHeat]);

  // Pre-normalise every metric onto the 0–4 scale once per result.
  const scaled = useMemo(() => {
    if (!heat) return null;
    const out = {};
    for (const [name, m] of Object.entries(METRICS)) {
      const rows = heat[m.key];
      out[name] = m.edges ? rows.map((row) => row.map((v) => toRiskScale(v, m.edges))) : rows;
    }
    return out;
  }, [heat]);

  // ---- heatmap values for the current slider hour (cheap; runs every animation frame)
  useEffect(() => {
    if (!scaled || !showHeat) return;
    const rows = scaled[metric];
    layers.current.heat.setValues(rows.map((_, i) => valueAt(rows, i, hour)));
  }, [scaled, metric, hour, showHeat]);

  // ---- truck position on the selected route at the slider time
  useEffect(() => {
    const map = mapRef.current;
    const route = result?.routes.find((r) => r.id === selectedId);
    if (!route || !heat) {
      layers.current.truck?.remove();
      layers.current.truck = null;
      return;
    }
    const t = (Date.parse(heat.start) + hour * 3600e3 - Date.parse(route.departure)) / 1000;
    const pos = positionAt(route.track, t);
    if (!pos) return;
    if (!layers.current.truck) {
      layers.current.truck = L.marker(pos, {
        icon: L.divIcon({ className: "truck", html: '<span aria-hidden="true"></span>', iconSize: [22, 22], iconAnchor: [11, 11] }),
        zIndexOffset: 2000,
        interactive: false,
      }).addTo(map);
    } else {
      layers.current.truck.setLatLng(pos);
    }
  }, [result, selectedId, hour, heat]);

  return <div ref={el} className="map" role="region" aria-label="Map of route options and weather" />;
}
