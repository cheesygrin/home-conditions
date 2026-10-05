"""Severity levels and how each one reaches the owner.

The design principle is silence: only Critical and Urgent interrupt anyone.
Everything else waits for the weekly report or is only logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import IntEnum


class Severity(IntEnum):
    """Ordered so that a higher value means more consequence (Critical > Info)."""

    INFO = 0
    MONITOR = 1
    URGENT = 2
    CRITICAL = 3

    @property
    def label(self) -> str:
        return self.name.capitalize()

    @property
    def meaning(self) -> str:
        return MEANINGS[self]

    @property
    def delivery(self) -> DeliveryPolicy:
        return DELIVERY[self]

    @classmethod
    def parse(cls, value: str | Severity) -> Severity:
        """Accept 'Critical', 'critical' or a Severity, as config files mix them."""
        if isinstance(value, Severity):
            return value
        try:
            return cls[value.strip().upper()]
        except KeyError:
            raise ValueError(f"unknown severity {value!r}") from None


@dataclass(frozen=True)
class DeliveryPolicy:
    """How and how fast a finding of a given severity reaches people."""

    channels: tuple[str, ...]
    """Push channels, e.g. ("sms", "email"). Empty means no push at all."""

    max_delay: timedelta | None
    """Latest acceptable send time after the finding. None means not pushed."""

    dispatch_button: bool
    """Offer one-tap 'send the evidence pack to a vendor'."""

    in_weekly_report: bool
    """Listed in the weekly visit report (all pushed findings are too)."""

    log_only: bool = False


MEANINGS: dict[Severity, str] = {
    Severity.CRITICAL: "Damage happening now",
    Severity.URGENT: "Damage likely within 48 hours",
    Severity.MONITOR: "Could become a problem",
    Severity.INFO: "Normal change (lighting, season)",
}

DELIVERY: dict[Severity, DeliveryPolicy] = {
    Severity.CRITICAL: DeliveryPolicy(
        channels=("sms", "email"),
        max_delay=timedelta(0),
        dispatch_button=True,
        in_weekly_report=True,
    ),
    Severity.URGENT: DeliveryPolicy(
        channels=("sms",),
        max_delay=timedelta(hours=1),
        dispatch_button=False,
        in_weekly_report=True,
    ),
    Severity.MONITOR: DeliveryPolicy(
        channels=(),
        max_delay=None,
        dispatch_button=False,
        in_weekly_report=True,
    ),
    Severity.INFO: DeliveryPolicy(
        channels=(),
        max_delay=None,
        dispatch_button=False,
        in_weekly_report=False,
        log_only=True,
    ),
}


def should_push(severity: Severity) -> bool:
    """True when the finding interrupts the owner instead of waiting for the report."""
    return bool(severity.delivery.channels)
