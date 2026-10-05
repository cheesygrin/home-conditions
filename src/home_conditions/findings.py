"""The Finding record that rules produce and the language tools sort and check."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from home_conditions.severity import Severity


@dataclass(frozen=True)
class Finding:
    rule_id: str
    """Which rule fired, e.g. "growth_risk"."""

    category: str
    """What kind of condition, used for consequence ranking, e.g. "water"."""

    severity: Severity
    title: str
    detail: str
    """What was observed, with the measured numbers."""

    recommendation: str
    """Who to call and what to have them evaluate."""

    specialist: str | None = None
    device_ids: tuple[str, ...] = ()
    started_at: datetime | None = None
    ongoing: bool = True
    evidence: dict[str, Any] = field(default_factory=dict)

    def text(self) -> str:
        """All owner-facing text in one string, for the language linter."""
        return "\n".join(part for part in (self.title, self.detail, self.recommendation) if part)
