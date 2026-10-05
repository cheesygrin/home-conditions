"""Expected-life table and serial-number date decoding with a confidence score.

Guardrail: a decoded date under the confidence bar is asked, never stated.
Use needs_confirmation() before telling an owner how old something is.

The packaged serial rules are fictitious samples that show the format. Real
rules must come from manufacturers' public documentation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

CONFIDENCE_BAR = 0.8
"""Decoded dates below this confidence must be confirmed by the owner."""

MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def _read_yaml(name: str, path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return yaml.safe_load(resources.files("home_conditions.data").joinpath(name).read_text())
    return yaml.safe_load(Path(path).read_text())


# ---------------------------------------------------------------------------
# Expected life
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LifeExpectancy:
    component_type: str
    label: str
    low: int
    high: int
    notes: str = ""


@cache
def _default_life_table() -> dict[str, LifeExpectancy]:
    return load_life_table()


def load_life_table(path: str | Path | None = None) -> dict[str, LifeExpectancy]:
    data = _read_yaml("appliance_life.yaml", path)
    if data.get("version") != 1:
        raise ValueError(f"unsupported appliance life table version {data.get('version')!r}")
    table = {}
    for key, entry in data["components"].items():
        low, high = entry["expected_life_years"]
        if not 0 < low <= high:
            raise ValueError(f"{key}: expected_life_years must be [low, high] with low <= high")
        table[key] = LifeExpectancy(key, entry["label"], low, high, entry.get("notes", ""))
    return table


@dataclass(frozen=True)
class AgeAssessment:
    component_type: str
    label: str
    age_years: float
    expected_low: int
    expected_high: int
    status: str
    """"within", "end_of_life_range" or "past"."""

    month_assumed: bool
    """True when the month was unknown and mid-year was assumed."""

    @property
    def fraction_of_life(self) -> float:
        """Age as a share of the high end of expected life; 1.0 = at the limit."""
        return self.age_years / self.expected_high


def assess_age(
    component_type: str,
    year: int,
    month: int | None,
    today: date | None = None,
    table: dict[str, LifeExpectancy] | None = None,
) -> AgeAssessment:
    """Compare a manufacture date against the expected-life range for its type."""
    today = today or date.today()
    life = (table or _default_life_table())[component_type]
    made = date(year, month or 6, 15)
    age = max(0.0, (today - made).days / 365.25)
    if age < life.low:
        status = "within"
    elif age <= life.high:
        status = "end_of_life_range"
    else:
        status = "past"
    return AgeAssessment(
        component_type, life.label, round(age, 1), life.low, life.high, status, month is None
    )


# ---------------------------------------------------------------------------
# Serial decoding
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SerialRule:
    id: str
    brand: str
    pattern: re.Pattern[str]
    year: dict[str, Any]
    confidence: float
    month: dict[str, Any] | None = None
    week: dict[str, Any] | None = None
    brand_aliases: tuple[str, ...] = ()
    applies_to: tuple[str, ...] = ()
    min_year: int = 1960
    source: str = ""

    def matches_brand(self, brand: str) -> bool:
        wanted = brand.strip().lower()
        names = [self.brand.lower(), *(a.lower() for a in self.brand_aliases)]
        return any(wanted == n or wanted.startswith(n + " ") for n in names)


@dataclass(frozen=True)
class DecodedDate:
    rule_id: str
    brand: str
    year: int
    month: int | None
    confidence: float
    explanation: str
    notes: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"{MONTH_NAMES[self.month - 1]} {self.year}" if self.month else str(self.year)


def load_serial_rules(path: str | Path | None = None) -> list[SerialRule]:
    data = _read_yaml("serial_rules.yaml", path)
    if data.get("version") != 1:
        raise ValueError(f"unsupported serial rules version {data.get('version')!r}")
    rules = []
    for entry in data["rules"]:
        pattern = re.compile(entry["pattern"])
        if "year" not in pattern.groupindex:
            raise ValueError(f"{entry['id']}: pattern needs a named group 'year'")
        if not 0 <= entry["confidence"] <= 1:
            raise ValueError(f"{entry['id']}: confidence must be between 0 and 1")
        rules.append(
            SerialRule(
                id=entry["id"],
                brand=entry["brand"],
                pattern=pattern,
                year=entry["year"],
                month=entry.get("month"),
                week=entry.get("week"),
                confidence=float(entry["confidence"]),
                brand_aliases=tuple(entry.get("brand_aliases") or ()),
                applies_to=tuple(entry.get("applies_to") or ()),
                min_year=int(entry.get("min_year", 1960)),
                source=entry.get("source", ""),
            )
        )
    return rules


@cache
def _default_serial_rules() -> tuple[SerialRule, ...]:
    return tuple(load_serial_rules())


def normalize_serial(serial: str) -> str:
    return re.sub(r"[\s\-]", "", serial).upper()


def _year_candidates(spec: dict[str, Any], raw: str, min_year: int, today: date) -> list[int]:
    fmt = spec["format"]
    if fmt == "YYYY":
        years = [int(raw)]
    elif fmt == "YY":
        value = int(raw)
        recent = 2000 + value
        years = [recent if recent <= today.year else 1900 + value]
    elif fmt == "Y":
        digit = int(raw)
        years = [y for y in range(min_year, today.year + 1) if y % 10 == digit]
    elif fmt == "letter":
        if raw not in spec["map"]:
            return []
        base = int(spec["map"][raw])
        cycle = spec.get("cycle_years")
        if cycle:
            first = base - ((base - min_year) // cycle) * cycle
            years = list(range(first, today.year + 1, cycle))
        else:
            years = [base]
    else:
        raise ValueError(f"unknown year format {fmt!r}")
    return [y for y in years if min_year <= y <= today.year]


def _month(rule: SerialRule, groups: dict[str, str], year: int) -> int | None:
    if rule.month and groups.get("month") is not None:
        raw = groups["month"]
        value = rule.month["map"].get(raw) if rule.month["format"] == "letter" else int(raw)
        return value if value and 1 <= value <= 12 else -1
    if rule.week and groups.get("week") is not None:
        week = int(groups["week"])
        if not 1 <= week <= 53:
            return -1
        return (date(year, 1, 1) + timedelta(weeks=week - 1)).month
    return None


def decode_serial(
    serial: str,
    brand: str | None = None,
    component_type: str | None = None,
    today: date | None = None,
    rules: list[SerialRule] | tuple[SerialRule, ...] | None = None,
) -> list[DecodedDate]:
    """Every plausible manufacture date for a serial, most confident first.

    Confidence starts at the rule's own value and is split evenly when a code
    repeats (a one-digit year matches every decade). Without a brand, every rule
    is tried and confidence is halved, because a pattern match alone is weak
    evidence. Dates in the future or before the rule's min_year are dropped.
    """
    today = today or date.today()
    rules = _default_serial_rules() if rules is None else rules
    normalized = normalize_serial(serial)
    results: list[DecodedDate] = []

    for rule in rules:
        if brand and not rule.matches_brand(brand):
            continue
        if component_type and rule.applies_to and component_type not in rule.applies_to:
            continue
        match = rule.pattern.fullmatch(normalized)
        if not match:
            continue
        groups = match.groupdict()
        candidates = []
        for year in _year_candidates(rule.year, groups["year"], rule.min_year, today):
            month = _month(rule, groups, year)
            if month == -1:
                break  # month or week code out of range: the rule doesn't really match
            if (year, month or 1) > (today.year, today.month):
                continue
            candidates.append((year, month))
        if not candidates:
            continue

        confidence = rule.confidence / len(candidates)
        notes = []
        if len(candidates) > 1:
            notes.append(f"code repeats; {len(candidates)} possible years")
        if not brand:
            confidence *= 0.5
            notes.append("brand not given; matched on pattern alone")
        for year, month in candidates:
            label = f"{MONTH_NAMES[month - 1]} {year}" if month else str(year)
            results.append(
                DecodedDate(
                    rule_id=rule.id,
                    brand=rule.brand,
                    year=year,
                    month=month,
                    confidence=round(confidence, 3),
                    explanation=f"{rule.brand} serial {normalized} decodes to {label} ({rule.id})",
                    notes=tuple(notes),
                )
            )

    return sorted(results, key=lambda d: (-d.confidence, -d.year))


def needs_confirmation(decoded: list[DecodedDate], bar: float = CONFIDENCE_BAR) -> bool:
    """True when the owner must confirm the date before anyone states it."""
    return not decoded or decoded[0].confidence < bar
