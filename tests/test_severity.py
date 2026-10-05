from datetime import timedelta

import pytest

from home_conditions.severity import Severity, should_push


def test_order_runs_from_info_to_critical():
    assert Severity.INFO < Severity.MONITOR < Severity.URGENT < Severity.CRITICAL
    assert max(Severity) is Severity.CRITICAL


def test_critical_is_sms_and_email_now_with_dispatch():
    policy = Severity.CRITICAL.delivery
    assert set(policy.channels) == {"sms", "email"}
    assert policy.max_delay == timedelta(0)
    assert policy.dispatch_button


def test_urgent_is_sms_within_the_hour():
    policy = Severity.URGENT.delivery
    assert policy.channels == ("sms",)
    assert policy.max_delay == timedelta(hours=1)
    assert not policy.dispatch_button


def test_monitor_waits_for_weekly_report_and_info_is_logged_only():
    assert not should_push(Severity.MONITOR)
    assert Severity.MONITOR.delivery.in_weekly_report
    assert not should_push(Severity.INFO)
    assert Severity.INFO.delivery.log_only
    assert not Severity.INFO.delivery.in_weekly_report


def test_labels_and_meanings():
    assert Severity.URGENT.label == "Urgent"
    assert Severity.CRITICAL.meaning == "Damage happening now"


@pytest.mark.parametrize("text", ["Critical", "critical", " CRITICAL "])
def test_parse_accepts_config_spellings(text):
    assert Severity.parse(text) is Severity.CRITICAL


def test_parse_rejects_unknown():
    with pytest.raises(ValueError, match="unknown severity"):
        Severity.parse("Severe")
