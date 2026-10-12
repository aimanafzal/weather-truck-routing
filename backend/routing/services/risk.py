"""Weather risk classification, exactly as specified in the assessment brief.

Levels (index = numeric score used for averaging):
    0 Low, 1 Moderate, 2 High, 3 Severe, 4 No Travel

Thresholds
    Wind (mph):     <25 | 25-34 | 35-44 | 45-54 | >=55
    Rain (in/hr):   <0.10 | 0.10-0.25 | 0.25-0.50 | 0.50-1.00 | >1.00
    Snow (in/hr):   <0.5 | 0.5-1.0 | 1.0-2.0 | 2.0-3.0 | >3.0

Boundary handling: a value equal to a band's lower bound belongs to that band
(e.g. wind 35.0 -> High, rain 0.25 -> High). The top band uses the brief's own
operators: wind is No Travel at >=55, rain/snow only when strictly above 1.00 / 3.0.

Load rules (applied on top of the weather level, never lowering it)
    wind >= 55                    -> No Travel (any load)
    wind 45-54 and load > 30,000  -> No Travel
    wind 35-44 and load > 40,000  -> Severe
"""
from __future__ import annotations

from dataclasses import dataclass, field

LOW, MODERATE, HIGH, SEVERE, NO_TRAVEL = range(5)
LEVEL_NAMES = ["Low", "Moderate", "High", "Severe", "No Travel"]


def _band(value: float, moderate: float, high: float, severe: float, no_travel: float, inclusive_top: bool) -> int:
    if value < moderate:
        return LOW
    if value < high:
        return MODERATE
    if value < severe:
        return HIGH
    if value > no_travel or (inclusive_top and value >= no_travel):
        return NO_TRAVEL
    return SEVERE


def wind_level(mph: float) -> int:
    return _band(mph, 25, 35, 45, 55, inclusive_top=True)


def rain_level(in_per_hr: float) -> int:
    return _band(in_per_hr, 0.10, 0.25, 0.50, 1.00, inclusive_top=False)


def snow_level(in_per_hr: float) -> int:
    return _band(in_per_hr, 0.5, 1.0, 2.0, 3.0, inclusive_top=False)


@dataclass
class RiskAssessment:
    level: int
    wind: int
    rain: int
    snow: int
    reasons: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return LEVEL_NAMES[self.level]

    def as_dict(self) -> dict:
        return {
            "level": self.name,
            "score": self.level,
            "factors": {
                "wind": LEVEL_NAMES[self.wind],
                "rain": LEVEL_NAMES[self.rain],
                "snow": LEVEL_NAMES[self.snow],
            },
            "reasons": self.reasons,
        }


def assess(wind_mph: float, rain_in_hr: float, snow_in_hr: float, load_lb: float) -> RiskAssessment:
    w, r, s = wind_level(wind_mph), rain_level(rain_in_hr), snow_level(snow_in_hr)
    level = max(w, r, s)
    reasons: list[str] = []

    for lvl, label in ((w, f"Wind {wind_mph:.0f} mph"), (r, f"Rain {rain_in_hr:.2f} in/hr"), (s, f"Snow {snow_in_hr:.2f} in/hr")):
        if lvl == level and lvl > LOW:
            reasons.append(f"{label} → {LEVEL_NAMES[lvl]}")

    # Load rules
    if wind_mph >= 55:
        load_level = NO_TRAVEL  # already No Travel by the wind band; listed for clarity
    elif wind_mph >= 45 and load_lb > 30_000:
        load_level = NO_TRAVEL
        reasons.append(f"Wind {wind_mph:.0f} mph with load {load_lb:,.0f} lb (>30,000) → No Travel")
    elif wind_mph >= 35 and load_lb > 40_000:
        load_level = SEVERE
        reasons.append(f"Wind {wind_mph:.0f} mph with load {load_lb:,.0f} lb (>40,000) → Severe")
    else:
        load_level = LOW

    if load_level > level:
        level = load_level
    if not reasons:
        reasons.append("Conditions within Low thresholds")
    return RiskAssessment(level=level, wind=w, rain=r, snow=s, reasons=reasons)
