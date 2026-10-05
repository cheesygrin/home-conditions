"""Sample rules: active water, freeze, and outage, plus the registry."""

from datetime import UTC, datetime, timedelta

import pytest

from home_conditions.rules import (
    Context,
    Device,
    DeviceStatusEvent,
    Observations,
    RulesConfig,
    SensorReading,
    evaluate,
    register_rule,
    registered_rule_ids,
)
from home_conditions.severity import Severity

NOW = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)


def test_sample_rules_are_registered():
    assert {"active_water", "freeze", "outage"} <= set(registered_rule_ids())


def test_flood_sensor_wet_is_critical():
    readings = [SensorReading(NOW, "flood-1", flood_wet=True)]
    (finding,) = evaluate(Observations(readings=readings), Context(now=NOW))
    assert finding.rule_id == "active_water"
    assert finding.severity is Severity.CRITICAL
    assert "still reads wet" in finding.detail


def test_freeze_uses_the_sample_threshold():
    cold = SensorReading(NOW, "temp-1", temperature_f=31)
    warm = SensorReading(NOW, "temp-1", temperature_f=33)
    (finding,) = evaluate(Observations(readings=[cold]), Context(now=NOW))
    assert finding.rule_id == "freeze"
    assert "32F" in finding.detail
    assert evaluate(Observations(readings=[warm]), Context(now=NOW)) == []


def test_outage_uses_the_sample_five_minute_threshold():
    devices = [Device("a", "sensor", "A"), Device("b", "sensor", "B")]
    short = NOW - timedelta(minutes=4)
    long = NOW - timedelta(minutes=6)

    def events(start):
        return [
            DeviceStatusEvent(start, "a", online=False),
            DeviceStatusEvent(start, "b", online=False),
        ]

    assert evaluate(
        Observations(devices=devices, status_events=events(short)), Context(now=NOW)
    ) == []
    (finding,) = evaluate(
        Observations(devices=devices, status_events=events(long)), Context(now=NOW)
    )
    assert finding.rule_id == "outage"
    assert finding.ongoing


def test_unknown_rule_id_is_rejected(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text("rules:\n  not_a_rule:\n    enabled: true\n")
    with pytest.raises(ValueError, match="unknown rule"):
        RulesConfig.load(path)


def test_a_registered_rule_without_a_config_block_is_skipped():
    def extra(ix, ctx, cfg):
        raise AssertionError("extra rule ran")

    register_rule("extra", extra)
    assert evaluate(Observations(), Context(now=NOW)) == []
