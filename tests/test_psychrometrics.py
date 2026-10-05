from datetime import UTC, datetime, timedelta

import pytest

from home_conditions.psychrometrics import (
    c_to_f,
    dew_point_f,
    f_to_c,
    longest_run,
    relative_humidity,
    slope_per_hour,
    sustained_runs,
)

T0 = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)


def series(values, step_minutes=10):
    return [(T0 + timedelta(minutes=i * step_minutes), v) for i, v in enumerate(values)]


def test_unit_conversions_round_trip():
    assert f_to_c(212) == pytest.approx(100)
    assert c_to_f(-40) == pytest.approx(-40)


@pytest.mark.parametrize(
    ("temp_f", "rh", "expected_dew_f"),
    [
        (77.0, 50.0, 57.0),  # 25 C, 50% -> 13.9 C
        (68.0, 100.0, 68.0),  # saturated air: dew point equals temperature
        (90.0, 70.0, 79.0),
    ],
)
def test_dew_point_matches_reference_values(temp_f, rh, expected_dew_f):
    assert dew_point_f(temp_f, rh) == pytest.approx(expected_dew_f, abs=0.5)


def test_relative_humidity_inverts_dew_point():
    dew = dew_point_f(80.0, 65.0)
    assert relative_humidity(80.0, dew) == pytest.approx(65.0, abs=0.01)
    assert relative_humidity(70.0, 75.0) == 100.0  # capped


@pytest.mark.parametrize("rh", [0, -5, 101])
def test_dew_point_rejects_impossible_humidity(rh):
    with pytest.raises(ValueError):
        dew_point_f(75.0, rh)


def test_sustained_runs_split_on_condition():
    runs = sustained_runs(series([55, 62, 63, 64, 58, 61, 62]), lambda v: v > 60)
    assert [r.count for r in runs] == [3, 2]
    assert runs[0].duration == timedelta(minutes=20)
    assert (runs[0].first_value, runs[0].last_value) == (62, 64)


def test_sustained_runs_break_on_data_gap():
    points = series([65, 65, 65]) + [
        (T0 + timedelta(hours=3), 65),
        (T0 + timedelta(hours=3, minutes=10), 65),
    ]
    runs = sustained_runs(points, lambda v: v > 60, max_gap=timedelta(hours=1))
    assert len(runs) == 2


def test_sustained_runs_sort_unordered_input():
    points = list(reversed(series([61, 62, 63])))
    assert sustained_runs(points, lambda v: v > 60)[0].start == T0


def test_longest_run_and_empty_series():
    assert longest_run(series([61, 50, 61, 62, 63]), lambda v: v > 60).count == 3
    assert longest_run([], lambda v: True) is None


def test_slope_per_hour():
    assert slope_per_hour(series([50, 51, 52, 53, 54, 55, 56])) == pytest.approx(6.0)
    assert slope_per_hour(series([50])) == 0.0
