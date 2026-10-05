"""Dew point, humidity trends and sustained-threshold detection.

Temperatures are Fahrenheit throughout, because that is what owners and
US thermostats use. Relative humidity is a percentage, 0-100.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

# Magnus formula constants (Alduchov and Eskridge, 1996). Accurate to well under
# 1 F across the indoor range we care about (roughly -40 F to 120 F).
_A = 17.625
_B = 243.04  # degrees C

Point = tuple[datetime, float]


def f_to_c(temp_f: float) -> float:
    return (temp_f - 32.0) * 5.0 / 9.0


def c_to_f(temp_c: float) -> float:
    return temp_c * 9.0 / 5.0 + 32.0


def dew_point_f(temp_f: float, rh_pct: float) -> float:
    """Dew point in F from dry-bulb temperature in F and relative humidity in %."""
    if not 0 < rh_pct <= 100:
        raise ValueError(f"relative humidity must be in (0, 100], got {rh_pct}")
    t = f_to_c(temp_f)
    gamma = math.log(rh_pct / 100.0) + _A * t / (_B + t)
    return c_to_f(_B * gamma / (_A - gamma))


def relative_humidity(temp_f: float, dew_point: float) -> float:
    """Relative humidity in % from temperature and dew point (both F). Capped at 100."""
    t, td = f_to_c(temp_f), f_to_c(dew_point)
    rh = 100.0 * math.exp(_A * td / (_B + td) - _A * t / (_B + t))
    return min(rh, 100.0)


@dataclass(frozen=True)
class Run:
    """A stretch of consecutive readings that all met a condition."""

    start: datetime
    end: datetime
    first_value: float
    last_value: float
    count: int

    @property
    def duration(self) -> timedelta:
        return self.end - self.start


def sustained_runs(
    points: Sequence[Point],
    predicate: Callable[[float], bool],
    max_gap: timedelta = timedelta(hours=1),
) -> list[Run]:
    """Split a time series into runs where ``predicate(value)`` holds.

    A run's duration is first matching reading to last matching reading, so it
    never claims time we have no data for. A gap between readings longer than
    ``max_gap`` ends the run for the same reason: a sensor that went quiet for
    three hours can't vouch for those hours.
    """
    runs: list[Run] = []
    current: list[Point] = []
    previous_at: datetime | None = None

    def close() -> None:
        if current:
            runs.append(
                Run(current[0][0], current[-1][0], current[0][1], current[-1][1], len(current))
            )
            current.clear()

    for at, value in sorted(points, key=lambda p: p[0]):
        if previous_at is not None and at - previous_at > max_gap:
            close()
        if predicate(value):
            current.append((at, value))
        else:
            close()
        previous_at = at
    close()
    return runs


def longest_run(
    points: Sequence[Point],
    predicate: Callable[[float], bool],
    max_gap: timedelta = timedelta(hours=1),
) -> Run | None:
    runs = sustained_runs(points, predicate, max_gap)
    return max(runs, key=lambda r: r.duration, default=None)


def slope_per_hour(points: Sequence[Point]) -> float:
    """Least-squares trend of the series in units per hour. 0.0 if under two points."""
    if len(points) < 2:
        return 0.0
    t0 = points[0][0]
    xs = [(at - t0).total_seconds() / 3600.0 for at, _ in points]
    ys = [value for _, value in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / sxx


def values_between(points: Sequence[Point], start: datetime, end: datetime) -> list[Point]:
    """Readings with start <= time <= end, in time order."""
    return sorted((p for p in points if start <= p[0] <= end), key=lambda p: p[0])
