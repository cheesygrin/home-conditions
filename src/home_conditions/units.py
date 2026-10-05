"""Display units and storm names.

The rules engine stays in Fahrenheit. These helpers convert only the numbers
an owner reads or hears. A degree change ("4F over") is scaled by 5/9. An
absolute temperature ("82F") is converted with the usual offset.

Unit preference defaults from the country: Fahrenheit for the United States,
Liberia and Myanmar, Celsius everywhere else. A blank country is treated as
the United States so an older home keeps Fahrenheit.

Storm mode is the product name. The regional word is the basin name when the
country sits in that basin, and "storm" otherwise. For the United States a
coastal state, or a blank region, uses "hurricane"; any other state code uses
"storm".
"""

from __future__ import annotations

import re

from home_conditions.psychrometrics import c_to_f, f_to_c

FAHRENHEIT_COUNTRIES = frozenset({"US", "LR", "MM"})

# Basin membership for owner-facing copy. Countries not listed say "storm".
HURRICANE_COUNTRIES = frozenset(
    {
        "US",
        "MX",
        "BS",
        "CU",
        "JM",
        "HT",
        "DO",
        "PR",
        "AG",
        "BB",
        "BZ",
        "HN",
        "NI",
        "CR",
        "PA",
        "GT",
        "SV",
        "KY",
        "TC",
        "BM",
        "GD",
        "LC",
        "VC",
        "KN",
        "DM",
        "TT",
        "AW",
        "CW",
        "AI",
        "MS",
        "VG",
        "VI",
    }
)
TYPHOON_COUNTRIES = frozenset(
    {"JP", "PH", "CN", "TW", "KR", "KP", "VN", "HK", "MO", "GU", "MP"}
)
CYCLONE_COUNTRIES = frozenset(
    {
        "AU",
        "NZ",
        "IN",
        "BD",
        "LK",
        "MM",
        "PK",
        "MZ",
        "MG",
        "MU",
        "FJ",
        "PG",
        "SB",
        "VU",
        "WS",
        "TO",
        "NC",
        "SC",
        "KM",
        "RE",
        "YT",
    }
)
US_HURRICANE_REGIONS = frozenset(
    {
        "AL",
        "CT",
        "DE",
        "FL",
        "GA",
        "HI",
        "LA",
        "MA",
        "MD",
        "ME",
        "MS",
        "NC",
        "NH",
        "NJ",
        "NY",
        "RI",
        "SC",
        "TX",
        "VA",
    }
)

_TEMP = re.compile(r"(?P<num>-?\d+(?:\.\d+)?)F(?P<delta>\s+over\b)?")


def _code(country: str | None) -> str:
    code = (country or "").strip().upper()
    return code if len(code) == 2 and code.isalpha() else "US"


def default_units(country: str | None) -> str:
    """``F`` or ``C`` from the country, when the owner has not chosen."""
    return "F" if _code(country) in FAHRENHEIT_COUNTRIES else "C"


def normalize_units(units: str | None, country: str | None = None) -> str:
    """``F`` or ``C``. An empty or unknown preference follows the country."""
    choice = (units or "").strip().upper()
    if choice in {"F", "C"}:
        return choice
    return default_units(country)


def _one_decimal(value: float) -> str:
    return f"{round(value, 1):.1f}"


def format_temperature(temp_f: float, units: str) -> str:
    """A stored Fahrenheit reading as the owner should see it, e.g. ``25.6°C``."""
    if normalize_units(units) == "C":
        return f"{_one_decimal(f_to_c(temp_f))}°C"
    return f"{_one_decimal(temp_f)}°F"


def speak_temperature(temp_f: float, units: str) -> str:
    """The same reading as a spoken phrase."""
    if normalize_units(units) == "C":
        return f"{_one_decimal(f_to_c(temp_f))} degrees Celsius"
    return f"{_one_decimal(temp_f)} degrees Fahrenheit"


def to_display_number(temp_f: float, units: str) -> float:
    value = f_to_c(temp_f) if normalize_units(units) == "C" else temp_f
    return round(value, 1)


def from_display(value: float, units: str) -> float:
    """A number the owner typed, back into Fahrenheit for storage."""
    return c_to_f(value) if normalize_units(units) == "C" else value


def localize_temperatures(text: str, units: str) -> str:
    """Rewrite ``82F`` and ``4F over`` in engine text. Fahrenheit text is unchanged."""
    if normalize_units(units) != "C":
        return text

    def repl(match: re.Match[str]) -> str:
        number = float(match.group("num"))
        if match.group("delta"):
            return f"{_one_decimal(number * 5.0 / 9.0)}°C over"
        return f"{_one_decimal(f_to_c(number))}°C"

    return _TEMP.sub(repl, text)


def storm_name(country: str | None, region: str = "") -> str:
    """``hurricane``, ``typhoon``, ``cyclone``, or ``storm``."""
    code = (country or "").strip().upper()
    area = (region or "").strip().upper()
    if code == "US":
        if not area or area in US_HURRICANE_REGIONS:
            return "hurricane"
        return "storm"
    if code in TYPHOON_COUNTRIES:
        return "typhoon"
    if code in CYCLONE_COUNTRIES:
        return "cyclone"
    if code in HURRICANE_COUNTRIES:
        return "hurricane"
    return "storm"


def storm_armed_line(country: str | None, region: str = "") -> str:
    """Owner-facing line when storm mode is armed."""
    name = storm_name(country, region)
    if name == "storm":
        return "Storm mode armed. Fresh baselines captured."
    return f"Storm mode armed ahead of a {name}. Fresh baselines captured."


def temperature_word(units: str) -> str:
    return "Celsius" if normalize_units(units) == "C" else "Fahrenheit"
