from datetime import UTC, datetime, timedelta

from home_conditions import synthetic

T0 = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)


def test_ac_failure_curve_spans_six_hours_and_climbs():
    readings = synthetic.ac_failure_curve(T0)
    assert readings[-1].at - readings[0].at == timedelta(hours=6)
    before = [r for r in readings if r.at - T0 < timedelta(hours=1)]
    assert all(abs(r.temperature_f - 78) <= 0.5 for r in before)
    assert readings[-1].temperature_f > 90
    assert readings[-1].humidity_pct > readings[len(before)].humidity_pct


def test_outage_takes_every_device_down_for_twenty_minutes():
    devices, events = synthetic.outage(T0)
    assert len(events) == 2 * len(devices)
    offline = [e for e in events if not e.online]
    online = [e for e in events if e.online]
    assert online[0].at - offline[0].at == timedelta(minutes=20)
    assert max(e.at for e in offline) < min(e.at for e in online)


def test_humidity_soak_holds_above_sixty_for_48_hours():
    readings = synthetic.humidity_soak(T0)
    assert readings[-1].at - readings[0].at == timedelta(hours=48)
    assert min(r.humidity_pct for r in readings) > 60


def test_fixtures_are_deterministic():
    assert synthetic.ac_failure_curve(T0) == synthetic.ac_failure_curve(T0)
    assert synthetic.humidity_soak(T0) == synthetic.humidity_soak(T0)
