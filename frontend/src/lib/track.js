/** Position on a route's track ([[secondsAfterDeparture, lat, lon], ...]) at time t. */
export function positionAt(track, t) {
  if (!track?.length) return null;
  if (t <= track[0][0]) return [track[0][1], track[0][2]];
  const last = track[track.length - 1];
  if (t >= last[0]) return [last[1], last[2]];
  let lo = 0;
  let hi = track.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (track[mid][0] <= t) lo = mid;
    else hi = mid;
  }
  const a = track[lo];
  const b = track[hi];
  const span = b[0] - a[0];
  const f = span > 0 ? (t - a[0]) / span : 0;
  return [a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

/** Heatmap value for point i at fractional hour h (linear between hourly values). */
export function valueAt(rows, i, h) {
  const row = rows[i];
  const h0 = Math.floor(h);
  const a = row[h0];
  const b = row[Math.min(row.length - 1, h0 + 1)];
  if (a == null) return b ?? null;
  if (b == null) return a;
  return a + (b - a) * (h - h0);
}
