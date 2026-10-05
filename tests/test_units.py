"""Display units and storm names. The rules engine is not converted here."""

from home_conditions.language import lint
from home_conditions.units import (
    default_units,
    format_temperature,
    localize_temperatures,
    storm_armed_line,
    storm_name,
)


def test_defaults_follow_the_country():
    assert default_units("US") == "F"
    assert default_units("lr") == "F"
    assert default_units("MM") == "F"
    assert default_units("FR") == "C"
    assert default_units("JP") == "C"
    assert default_units("") == "F"
    assert default_units(None) == "F"


def test_localize_converts_absolutes_and_deltas_separately():
    text = (
        "Indoor temperature at Hall has held at or above "
        "82F, 4F over the 78F set point, peaking at 84.2F."
    )
    assert localize_temperatures(text, "F") == text
    assert localize_temperatures(text, "C") == (
        "Indoor temperature at Hall has held at or above "
        "27.8°C, 2.2°C over the 25.6°C set point, peaking at 29.0°C."
    )
    assert format_temperature(78.0, "C") == "25.6°C"
    assert format_temperature(78.0, "F") == "78.0°F"


def test_storm_name_follows_the_basin():
    assert storm_name("US") == "hurricane"
    assert storm_name("US", "FL") == "hurricane"
    assert storm_name("US", "CO") == "storm"
    assert storm_name("JP") == "typhoon"
    assert storm_name("AU") == "cyclone"
    assert storm_name("MM") == "cyclone"
    assert storm_name("FR") == "storm"
    lines = [
        storm_armed_line("US", "FL"),
        storm_armed_line("JP"),
        storm_armed_line("AU"),
        storm_armed_line("FR"),
    ]
    assert lines[0] == "Storm mode armed ahead of a hurricane. Fresh baselines captured."
    assert "typhoon" in lines[1]
    assert "cyclone" in lines[2]
    assert lines[3] == "Storm mode armed. Fresh baselines captured."
    for line in lines:
        assert lint(line) == []
