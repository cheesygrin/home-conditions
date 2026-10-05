"""Synthetic sensor data for tests and clearly labeled demos.

Deterministic: the same arguments always give the same series. Anything built
from these must be labeled as emulated wherever an owner or judge sees it.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from home_conditions.rules import Device, DeviceStatusEvent, SensorReading

STEP = timedelta(minutes=10)


def _times(start: datetime, duration: timedelta, step: timedelta) -> list[datetime]:
    count = int(duration / step)
    return [start + i * step for i in range(count + 1)]


def ac_failure_curve(
    start: datetime,
    device_id: str = "temp-humidity-1",
    set_point_f: float = 78.0,
    hours: float = 6.0,
    fail_after: timedelta = timedelta(hours=1),
    heat_to_f: float = 92.0,
    step: timedelta = STEP,
) -> list[SensorReading]:
    """Six hours of a closed-up house whose AC stops cooling.

    Before the failure the thermostat holds the set point, cycling about 0.4 F
    every half hour, at 50% relative humidity. After it, temperature climbs
    toward heat_to_f (time constant 2 h) and humidity climbs toward 62%
    (time constant 2.5 h), as it does with no cooling or dehumidification.
    """
    readings = []
    for at in _times(start, timedelta(hours=hours), step):
        minutes = (at - start).total_seconds() / 60
        if at - start < fail_after:
            temp = set_point_f + 0.4 * math.sin(2 * math.pi * minutes / 30)
            rh = 50.0
        else:
            hours_failed = (at - start - fail_after).total_seconds() / 3600
            temp = set_point_f + (heat_to_f - set_point_f) * (1 - math.exp(-hours_failed / 2.0))
            rh = 50.0 + 12.0 * (1 - math.exp(-hours_failed / 2.5))
        readings.append(SensorReading(at, device_id, round(temp, 2), round(rh, 1)))
    return readings


def outage(
    start: datetime,
    devices: list[Device] | None = None,
    minutes: float = 20,
    stagger: timedelta = timedelta(seconds=30),
) -> tuple[list[Device], list[DeviceStatusEvent]]:
    """Every device drops within a minute or two and comes back after ``minutes``.

    Devices go offline ``stagger`` apart starting at ``start`` and reconnect in the
    same order starting at start + minutes, the pattern a whole-house power or
    internet loss produces.
    """
    devices = devices or [
        Device("cam-kitchen", "camera", "Kitchen"),
        Device("cam-front", "camera", "Front door"),
        Device("sensor-flood", "sensor", "Water heater flood"),
    ]
    back = start + timedelta(minutes=minutes)
    events = []
    for i, device in enumerate(devices):
        events.append(DeviceStatusEvent(start + i * stagger, device.id, online=False))
        events.append(DeviceStatusEvent(back + i * stagger, device.id, online=True))
    return devices, sorted(events, key=lambda e: e.at)


def humidity_soak(
    start: datetime,
    device_id: str = "temp-humidity-1",
    hours: float = 48.0,
    mean_rh: float = 65.0,
    temp_f: float = 80.0,
    step: timedelta = STEP,
) -> list[SensorReading]:
    """Forty-eight hours of humidity held above 60%, with a small daily swing.

    Relative humidity moves 2 points either side of mean_rh over a 24-hour
    cycle; temperature moves 1.5 F the opposite way, as it does indoors.
    """
    readings = []
    for at in _times(start, timedelta(hours=hours), step):
        phase = 2 * math.pi * (at - start).total_seconds() / 86400
        readings.append(
            SensorReading(
                at,
                device_id,
                temperature_f=round(temp_f + 1.5 * math.sin(phase), 2),
                humidity_pct=round(mean_rh - 2.0 * math.sin(phase), 1),
            )
        )
    return readings
