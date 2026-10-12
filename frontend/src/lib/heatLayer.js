import L from "leaflet";
import { rampColor } from "./risk.js";

/**
 * Corridor heatmap rendered on a canvas.
 *
 * Each redraw interpolates the sample points onto a coarse pixel grid (inverse-distance
 * weighting over nearby points only), colours each cell on the continuous 0–4 risk ramp,
 * fades it out with distance from the nearest sample (so the colour hugs the corridor),
 * and scales the small image up with smoothing. Costs a few ms, so the forecast slider can
 * redraw every animation frame.
 */
export const CorridorHeatLayer = L.Layer.extend({
  options: { cell: 6, opacity: 0.62, pane: "overlayPane" },

  initialize(options) {
    L.setOptions(this, options);
    this._points = [];
    this._values = [];
  },

  onAdd(map) {
    this._map = map;
    this._canvas = L.DomUtil.create("canvas", "heat-canvas leaflet-zoom-hide");
    this._canvas.style.pointerEvents = "none";
    this._canvas.style.opacity = this.options.opacity;
    this._small = document.createElement("canvas");
    map.getPane(this.options.pane).appendChild(this._canvas);
    map.on("moveend zoomend resize viewreset", this._reset, this);
    this._reset();
  },

  onRemove(map) {
    L.DomUtil.remove(this._canvas);
    map.off("moveend zoomend resize viewreset", this._reset, this);
  },

  /** points: [[lat, lon], ...]; spacing in miles between neighbouring samples. */
  setPoints(points, spacingMi) {
    this._points = points;
    this._spacingMi = spacingMi;
    this._reset();
    return this;
  },

  /** values: number|null per point on the 0–4 scale. */
  setValues(values) {
    this._values = values;
    this._draw();
    return this;
  },

  _reset() {
    if (!this._map) return;
    const size = this._map.getSize();
    const topLeft = this._map.containerPointToLayerPoint([0, 0]);
    L.DomUtil.setPosition(this._canvas, topLeft);
    const dpr = 1; // the image is upscaled and blurred anyway
    this._canvas.width = size.x * dpr;
    this._canvas.height = size.y * dpr;
    this._canvas.style.width = `${size.x}px`;
    this._canvas.style.height = `${size.y}px`;
    this._project();
    this._draw();
  },

  _project() {
    const map = this._map;
    this._px = this._points.map(([lat, lon]) => map.latLngToContainerPoint([lat, lon]));
    // Influence radius: ~1.6x the sample spacing, converted to pixels at the map centre.
    const c = map.getCenter();
    const p1 = map.latLngToContainerPoint(c);
    const p2 = map.latLngToContainerPoint([c.lat, c.lng + (this._spacingMi || 20) / (69.17 * Math.cos((c.lat * Math.PI) / 180))]);
    this._radius = Math.max(12, Math.abs(p2.x - p1.x) * 1.6);
    // Bucket projected points on a grid of radius-sized cells.
    const r = this._radius;
    const buckets = new Map();
    this._px.forEach((p, i) => {
      const key = `${Math.floor(p.x / r)},${Math.floor(p.y / r)}`;
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(i);
    });
    this._buckets = buckets;
  },

  _draw() {
    if (!this._map || !this._canvas) return;
    const ctx = this._canvas.getContext("2d");
    const W = this._canvas.width;
    const H = this._canvas.height;
    ctx.clearRect(0, 0, W, H);
    if (!this._px?.length || this._values.length !== this._px.length) return;

    const cell = this.options.cell;
    const gw = Math.ceil(W / cell);
    const gh = Math.ceil(H / cell);
    const small = this._small;
    small.width = gw;
    small.height = gh;
    const sctx = small.getContext("2d");
    const img = sctx.createImageData(gw, gh);
    const data = img.data;
    const r = this._radius;
    const r2 = r * r;
    const px = this._px;
    const vals = this._values;
    const buckets = this._buckets;

    for (let gy = 0; gy < gh; gy++) {
      const y = gy * cell + cell / 2;
      const by = Math.floor(y / r);
      for (let gx = 0; gx < gw; gx++) {
        const x = gx * cell + cell / 2;
        const bx = Math.floor(x / r);
        let wsum = 0;
        let vsum = 0;
        let dmin2 = Infinity;
        for (let oy = -1; oy <= 1; oy++) {
          for (let ox = -1; ox <= 1; ox++) {
            const list = buckets.get(`${bx + ox},${by + oy}`);
            if (!list) continue;
            for (let k = 0; k < list.length; k++) {
              const i = list[k];
              const v = vals[i];
              if (v == null) continue;
              const dx = px[i].x - x;
              const dy = px[i].y - y;
              const d2 = dx * dx + dy * dy;
              if (d2 > r2) continue;
              if (d2 < dmin2) dmin2 = d2;
              const w = 1 / (d2 + 25);
              wsum += w;
              vsum += w * v;
            }
          }
        }
        const o = (gy * gw + gx) * 4;
        if (wsum === 0) {
          data[o + 3] = 0;
          continue;
        }
        const v = vsum / wsum;
        const fade = 1 - Math.sqrt(dmin2) / r; // 1 at a sample, 0 at the edge of influence
        const [cr, cg, cb] = rampColor(v);
        data[o] = cr;
        data[o + 1] = cg;
        data[o + 2] = cb;
        // Calm weather stays faint so storms read at a glance.
        data[o + 3] = Math.round(255 * Math.min(1, fade * 1.6) * (0.28 + 0.72 * Math.min(1, v / 3)));
      }
    }
    sctx.putImageData(img, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.filter = `blur(${Math.round(cell * 0.8)}px)`;
    ctx.drawImage(small, 0, 0, gw * cell, gh * cell);
    ctx.filter = "none";
  },
});
