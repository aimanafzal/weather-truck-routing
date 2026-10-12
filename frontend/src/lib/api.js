// API base: same origin by default (Django serves the app). Set VITE_API_BASE when the
// frontend is hosted separately, e.g. https://truck-routing-api.onrender.com
const BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, options);
  } catch {
    throw new Error("Can't reach the server. Check your connection and try again.");
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON error page */
  }
  if (!res.ok) throw new Error(data?.error || `Request failed (HTTP ${res.status}).`);
  return data;
}

export function geocode(q, signal) {
  return request(`/api/geocode?q=${encodeURIComponent(q)}`, { signal }).then((d) => d.results);
}

export function planTrip(payload, signal) {
  return request("/api/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
}
