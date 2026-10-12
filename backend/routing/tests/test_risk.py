import pytest

from routing.services import risk
from routing.services.risk import HIGH, LOW, MODERATE, NO_TRAVEL, SEVERE


@pytest.mark.parametrize(
    "mph,expected",
    [(0, LOW), (24.9, LOW), (25, MODERATE), (34.9, MODERATE), (35, HIGH), (44.9, HIGH), (45, SEVERE), (54.9, SEVERE), (55, NO_TRAVEL), (80, NO_TRAVEL)],
)
def test_wind_bands(mph, expected):
    assert risk.wind_level(mph) == expected


@pytest.mark.parametrize(
    "rate,expected",
    [(0, LOW), (0.099, LOW), (0.10, MODERATE), (0.249, MODERATE), (0.25, HIGH), (0.499, HIGH), (0.50, SEVERE), (1.00, SEVERE), (1.01, NO_TRAVEL)],
)
def test_rain_bands(rate, expected):
    assert risk.rain_level(rate) == expected


@pytest.mark.parametrize(
    "rate,expected",
    [(0, LOW), (0.49, LOW), (0.5, MODERATE), (0.99, MODERATE), (1.0, HIGH), (1.99, HIGH), (2.0, SEVERE), (3.0, SEVERE), (3.01, NO_TRAVEL)],
)
def test_snow_bands(rate, expected):
    assert risk.snow_level(rate) == expected


def test_overall_is_worst_factor():
    a = risk.assess(wind_mph=10, rain_in_hr=0.3, snow_in_hr=0.6, load_lb=10_000)
    assert a.level == HIGH
    assert a.as_dict()["factors"] == {"wind": "Low", "rain": "High", "snow": "Moderate"}


def test_load_rule_wind_55_any_load():
    assert risk.assess(55, 0, 0, 0).level == NO_TRAVEL


def test_load_rule_45_54_heavy_is_no_travel():
    assert risk.assess(46, 0, 0, 30_001).level == NO_TRAVEL
    assert risk.assess(46, 0, 0, 30_000).level == SEVERE  # not > 30,000
    assert risk.assess(54.9, 0, 0, 45_000).level == NO_TRAVEL


def test_load_rule_35_44_very_heavy_is_severe():
    assert risk.assess(36, 0, 0, 40_001).level == SEVERE
    assert risk.assess(36, 0, 0, 40_000).level == HIGH
    assert risk.assess(34, 0, 0, 79_000).level == MODERATE  # below rule band


def test_load_rule_never_lowers_level():
    # heavy rain stays No Travel even though the wind/load rule only gives Severe
    assert risk.assess(40, 1.2, 0, 45_000).level == NO_TRAVEL


def test_reasons_explain_load_rule():
    reasons = risk.assess(47, 0, 0, 35_000).reasons
    assert any("30,000" in r for r in reasons)
