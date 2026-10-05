from datetime import date, timedelta

import pytest

from home_conditions.appliances import (
    CONFIDENCE_BAR,
    assess_age,
    decode_serial,
    load_life_table,
    load_serial_rules,
    needs_confirmation,
    normalize_serial,
)

TODAY = date.today()


def _years_ago(n: int) -> int:
    return TODAY.year - n


# --- expected life ----------------------------------------------------------


def test_life_table_loads_with_sane_ranges():
    table = load_life_table()
    assert table["water_heater_tank_gas"].low == 8
    assert all(entry.low <= entry.high for entry in table.values())


@pytest.mark.parametrize(
    ("years_ago", "status"),
    [(3, "within"), (10, "end_of_life_range"), (20, "past")],
)
def test_assess_age_status(years_ago, status):
    result = assess_age("water_heater_tank_gas", _years_ago(years_ago), 1, TODAY)
    assert result.status == status
    assert result.label == "Gas tank water heater"


def test_assess_age_assumes_mid_year_when_month_unknown():
    year = _years_ago(10)
    result = assess_age("ac_condenser", year, None, TODAY)
    made = date(year, 6, 15)
    expected = max(0.0, (TODAY - made).days / 365.25)
    assert result.month_assumed
    assert result.age_years == pytest.approx(round(expected, 1), abs=0.05)
    assert result.fraction_of_life == pytest.approx(result.age_years / result.expected_high)


def test_life_table_rejects_bad_ranges(tmp_path):
    path = tmp_path / "life.yaml"
    path.write_text(
        "version: 1\ncomponents:\n  x:\n    label: X\n    expected_life_years: [9, 3]\n"
    )
    with pytest.raises(ValueError, match="low <= high"):
        load_life_table(path)


# --- serial decoding --------------------------------------------------------


def test_month_year_rule_decodes_with_high_confidence():
    year = _years_ago(11)
    serial = f"03{year % 100:02d}A12345"
    decoded = decode_serial(serial, brand="Acme Water Products", today=TODAY)
    assert [(d.year, d.month) for d in decoded] == [(year, 3)]
    assert decoded[0].confidence == 0.9
    assert decoded[0].label == f"March {year}"
    assert not needs_confirmation(decoded)


def test_two_digit_year_picks_most_recent_century_not_in_future():
    decoded = decode_serial("1195A12345", brand="acme", today=TODAY)
    assert decoded[0].year == 1900 + 95
    assert decoded[0].month == 11


def test_serial_is_normalized_before_matching():
    year = _years_ago(11)
    raw = f" 03{year % 100:02d}-a12 345 "
    assert normalize_serial(raw) == f"03{year % 100:02d}A12345"
    assert decode_serial(raw, brand="Acme", today=TODAY)[0].year == year


def test_week_code_maps_to_month():
    year = _years_ago(8)
    decoded = decode_serial(f"{year % 100:02d}32AB1234", brand="Borealis Comfort", today=TODAY)
    expected_month = (date(year, 1, 1) + timedelta(weeks=31)).month
    assert (decoded[0].year, decoded[0].month) == (year, expected_month)


def test_repeating_letter_code_splits_confidence_and_asks():
    rule = next(r for r in load_serial_rules() if r.id == "cobalt-letters")
    base = int(rule.year["map"]["B"])
    cycle = int(rule.year["cycle_years"])
    first = base - ((base - rule.min_year) // cycle) * cycle
    expected = {
        y
        for y in range(first, TODAY.year + 1, cycle)
        if (y, 3) <= (TODAY.year, TODAY.month)
    }
    decoded = decode_serial("CB123456", brand="Cobalt Appliance", today=TODAY)
    assert {d.year for d in decoded} == expected
    assert all(d.month == 3 for d in decoded)
    assert decoded[0].confidence == pytest.approx(0.8 / len(decoded), abs=0.001)
    assert decoded[0].year == max(expected)
    assert needs_confirmation(decoded)
    assert "possible years" in decoded[0].notes[0]


def test_single_digit_year_gives_one_candidate_per_decade():
    decoded = decode_serial("D60412345", brand="Dynamo", today=TODAY)
    gaps = [a.year - b.year for a, b in zip(decoded, decoded[1:], strict=False)]
    assert gaps == [10] * (len(decoded) - 1)
    assert all(d.year % 10 == 6 and d.month == 4 for d in decoded)
    assert decoded[0].year == max(d.year for d in decoded)
    assert needs_confirmation(decoded)


def test_future_dates_are_dropped():
    if TODAY.month == 12:
        decoded = decode_serial("D60112345", brand="Dynamo", today=TODAY)
        assert TODAY.year in {d.year for d in decoded}
        return
    month = TODAY.month + 1
    decoded = decode_serial(f"D6{month:02d}12345", brand="Dynamo", today=TODAY)
    assert TODAY.year not in {d.year for d in decoded}


def test_out_of_range_month_means_no_match():
    assert decode_serial("1315A12345", brand="Acme", today=TODAY) == []


def test_unknown_brand_matches_nothing():
    assert decode_serial("0315A12345", brand="Someone Else", today=TODAY) == []


def test_without_brand_confidence_is_halved_and_confirmation_required():
    decoded = decode_serial("0315A12345", today=TODAY)
    assert decoded[0].confidence == pytest.approx(0.45)
    assert needs_confirmation(decoded)


def test_component_type_filters_rules():
    assert decode_serial("0315A12345", "Acme", component_type="ac_condenser", today=TODAY) == []
    assert decode_serial("0315A12345", "Acme", "water_heater_tank_gas", today=TODAY)


def test_nothing_decoded_needs_confirmation():
    assert needs_confirmation([])
    assert CONFIDENCE_BAR == 0.8


def test_sample_rules_are_marked_as_samples():
    for rule in load_serial_rules():
        assert "Fictitious sample" in rule.source


def test_rule_file_requires_a_year_group(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        "version: 1\nrules:\n  - id: x\n    brand: X\n    pattern: '^(?P<month>\\d{2})$'\n"
        "    year: {format: YY}\n    confidence: 0.5\n"
    )
    with pytest.raises(ValueError, match="named group 'year'"):
        load_serial_rules(path)
