"""Canonical macro indicator and release-family definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndicatorDefinition:
    key: str
    name: str
    family: str
    unit: str
    periodicity: str
    hotter_when_higher: bool
    bundle_weight: float
    description: str


INDICATORS: tuple[IndicatorDefinition, ...] = (
    IndicatorDefinition(
        "headline_mom",
        "Headline CPI MoM",
        "inflation",
        "%",
        "monthly",
        True,
        0.20,
        "All-items consumer prices, month over month.",
    ),
    IndicatorDefinition(
        "headline_yoy",
        "Headline CPI YoY",
        "inflation",
        "%",
        "monthly",
        True,
        0.20,
        "All-items consumer prices, year over year.",
    ),
    IndicatorDefinition(
        "core_mom",
        "Core CPI MoM",
        "inflation",
        "%",
        "monthly",
        True,
        0.35,
        "Consumer prices excluding food and energy, month over month.",
    ),
    IndicatorDefinition(
        "core_yoy",
        "Core CPI YoY",
        "inflation",
        "%",
        "monthly",
        True,
        0.25,
        "Consumer prices excluding food and energy, year over year.",
    ),
    IndicatorDefinition(
        "nonfarm_payrolls",
        "Nonfarm Payrolls",
        "employment",
        "thousand persons",
        "monthly",
        True,
        0.35,
        "Monthly change in U.S. nonfarm payroll employment.",
    ),
    IndicatorDefinition(
        "unemployment_rate",
        "Unemployment Rate",
        "employment",
        "%",
        "monthly",
        False,
        0.25,
        "U.S. unemployment rate; lower is oriented as a stronger labor signal.",
    ),
    IndicatorDefinition(
        "average_hourly_earnings_mom",
        "Average Hourly Earnings MoM",
        "wages",
        "%",
        "monthly",
        True,
        0.18,
        "Average hourly earnings, month over month.",
    ),
    IndicatorDefinition(
        "average_hourly_earnings_yoy",
        "Average Hourly Earnings YoY",
        "wages",
        "%",
        "monthly",
        True,
        0.17,
        "Average hourly earnings, year over year.",
    ),
    IndicatorDefinition(
        "labor_force_participation",
        "Labor Force Participation Rate",
        "employment",
        "%",
        "monthly",
        True,
        0.05,
        "Participation rate; interpretation is conditional and shown separately.",
    ),
    IndicatorDefinition(
        "fed_funds_lower",
        "Federal Funds Target Lower Bound",
        "monetary_policy",
        "%",
        "event",
        True,
        0.20,
        "Lower bound of the announced target range.",
    ),
    IndicatorDefinition(
        "fed_funds_upper",
        "Federal Funds Target Upper Bound",
        "monetary_policy",
        "%",
        "event",
        True,
        0.20,
        "Upper bound of the announced target range.",
    ),
    IndicatorDefinition(
        "statement_tone_score",
        "FOMC Statement Tone Score",
        "monetary_policy",
        "bounded score",
        "event",
        True,
        0.30,
        "Human-verified bounded coding of statement changes; never official data.",
    ),
    IndicatorDefinition(
        "press_conference_tone_score",
        "Chair Press Conference Tone Score",
        "monetary_policy",
        "bounded score",
        "event",
        True,
        0.30,
        "Human-verified bounded coding of the press conference; never official data.",
    ),
)

INDICATOR_BY_KEY = {item.key: item for item in INDICATORS}

RELEASE_INDICATORS: dict[str, tuple[str, ...]] = {
    "US_CPI": ("headline_mom", "headline_yoy", "core_mom", "core_yoy"),
    "US_NFP": (
        "nonfarm_payrolls",
        "unemployment_rate",
        "average_hourly_earnings_mom",
        "average_hourly_earnings_yoy",
        "labor_force_participation",
    ),
    "FOMC": (
        "fed_funds_lower",
        "fed_funds_upper",
        "statement_tone_score",
        "press_conference_tone_score",
    ),
}

RELEASE_TITLES = {
    "US_CPI": "美国消费者价格指数（CPI）",
    "US_NFP": "美国就业报告（非农）",
    "FOMC": "美联储利率决议与新闻发布会",
}
