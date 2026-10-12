import { describe, expect, it } from "vitest";
import { rampColor, toRiskScale, THRESHOLDS } from "./risk.js";
import { positionAt, valueAt } from "./track.js";
import { localInputToIso } from "./format.js";

describe("risk scale", () => {
  it("matches band thresholds", () => {
    expect(toRiskScale(0, THRESHOLDS.wind_mph)).toBe(0);
    expect(toRiskScale(25, THRESHOLDS.wind_mph)).toBeCloseTo(1);
    expect(toRiskScale(35, THRESHOLDS.wind_mph)).toBeCloseTo(2);
    expect(toRiskScale(55, THRESHOLDS.wind_mph)).toBe(4);
    expect(toRiskScale(0.5, THRESHOLDS.rain_in_hr)).toBeCloseTo(3);
    expect(toRiskScale(null, THRESHOLDS.rain_in_hr)).toBeNull();
  });
  it("ramps colours continuously", () => {
    expect(rampColor(0)).toEqual([58, 157, 93]);
    expect(rampColor(4)).toEqual([123, 44, 191]);
    expect(rampColor(0.5)[0]).toBeCloseTo((58 + 227) / 2);
  });
});

describe("track", () => {
  const track = [[0, 0, 0], [100, 1, 1], [200, 1, 1], [300, 2, 3]];
  it("interpolates and clamps", () => {
    expect(positionAt(track, -5)).toEqual([0, 0]);
    expect(positionAt(track, 50)).toEqual([0.5, 0.5]);
    expect(positionAt(track, 150)).toEqual([1, 1]); // stopped
    expect(positionAt(track, 999)).toEqual([2, 3]);
  });
  it("interpolates hourly values", () => {
    expect(valueAt([[0, 4, null]], 0, 0.5)).toBe(2);
    expect(valueAt([[0, 4, null]], 0, 1.5)).toBe(4);
  });
});

describe("format", () => {
  it("adds the local offset", () => {
    expect(localInputToIso("2026-10-12T08:30")).toMatch(/^2026-10-12T08:30:00[+-]\d\d:\d\d$/);
  });
});
