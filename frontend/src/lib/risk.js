// Risk levels and colours shared by the map, route cards and heatmap.
export const LEVELS = ["Low", "Moderate", "High", "Severe", "No Travel"];

export const LEVEL_COLORS = {
  Low: "#3A9D5D",
  Moderate: "#E3C34A",
  High: "#EF8A2E",
  Severe: "#D83A3A",
  "No Travel": "#7B2CBF",
};
export const UNKNOWN_COLOR = "#8A969E";

export const levelColor = (level) => LEVEL_COLORS[level] ?? UNKNOWN_COLOR;

// Same thresholds as backend/routing/services/risk.py (Moderate, High, Severe, No Travel lower bounds)
export const THRESHOLDS = {
  wind_mph: [25, 35, 45, 55],
  rain_in_hr: [0.1, 0.25, 0.5, 1.0],
  snow_in_hr: [0.5, 1.0, 2.0, 3.0],
};

/** Map a raw measurement onto the 0–4 risk scale, continuous inside each band. */
export function toRiskScale(value, edges) {
  if (value == null) return null;
  if (value < edges[0]) return (value / edges[0]) * 0.99;
  for (let k = 0; k < edges.length - 1; k++) {
    if (value < edges[k + 1]) return k + 1 + ((value - edges[k]) / (edges[k + 1] - edges[k])) * 0.99;
  }
  return 4;
}

// Colour ramp stops on the 0–4 scale (continuous interpolation for the heatmap).
const RAMP = [
  [0, [58, 157, 93]],
  [1, [227, 195, 74]],
  [2, [239, 138, 46]],
  [3, [216, 58, 58]],
  [4, [123, 44, 191]],
];

/** RGB for a continuous 0–4 risk value. */
export function rampColor(v) {
  if (v <= 0) return RAMP[0][1];
  if (v >= 4) return RAMP[4][1];
  const i = Math.floor(v);
  const t = v - i;
  const a = RAMP[i][1];
  const b = RAMP[i + 1][1];
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

export const METRICS = {
  risk: { label: "Overall risk", unit: "", key: "risk", edges: null },
  wind: { label: "Wind", unit: "mph", key: "wind_mph", edges: THRESHOLDS.wind_mph },
  rain: { label: "Rain", unit: "in/hr", key: "rain_in_hr", edges: THRESHOLDS.rain_in_hr },
  snow: { label: "Snow", unit: "in/hr", key: "snow_in_hr", edges: THRESHOLDS.snow_in_hr },
};
