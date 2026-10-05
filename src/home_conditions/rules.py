"""Rules engine: sensor series + vision results + context in, ranked findings out.

    from home_conditions.rules import Context, Observations, RulesConfig, evaluate

    findings = evaluate(observations, context)            # sample thresholds
    findings = evaluate(observations, context, RulesConfig.load("my_rules.yaml"))

All timestamps must be timezone-aware. Visitor windows and seasons are judged
in the property's local time zone (Context.timezone).
"""

from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from importlib import resources
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import yaml

from home_conditions.findings import Finding
from home_conditions.language import rank_findings
from home_conditions.severity import Severity
from home_conditions.vision import VisionResult

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Device:
    id: str
    kind: str
    """"camera" for anything with video; anything else is treated as a sensor."""

    name: str = ""

    @property
    def label(self) -> str:
        return self.name or self.id

@dataclass(frozen=True)
class SensorReading:
    """One reading or state change. Fill only the fields the device reports."""

    at: datetime
    device_id: str
    temperature_f: float | None = None
    humidity_pct: float | None = None
    flood_wet: bool | None = None
    freeze_alert: bool | None = None
    contact_open: bool | None = None

@dataclass(frozen=True)
class DeviceStatusEvent:
    at: datetime
    device_id: str
    online: bool

@dataclass(frozen=True)
class MotionEvent:
    at: datetime
    device_id: str
    subtype: str = "human"

@dataclass(frozen=True)
class Sweep:
    """One camera's vision result from one sweep (scheduled or event-driven)."""

    at: datetime
    device_id: str
    result: VisionResult

@dataclass
class Observations:
    devices: Sequence[Device] = ()
    readings: Sequence[SensorReading] = ()
    status_events: Sequence[DeviceStatusEvent] = ()
    motion_events: Sequence[MotionEvent] = ()
    sweeps: Sequence[Sweep] = ()

    def timestamps(self) -> Iterable[datetime]:
        for group in (self.readings, self.status_events, self.motion_events, self.sweeps):
            for item in group:
                yield item.at

class VisitorWindow(Protocol):
    label: str

    def contains(self, local: datetime) -> bool: ...

@dataclass(frozen=True)
class WeeklyWindow:
    """A recurring visit, e.g. pool service Tuesdays 9:00-11:00.

    weekdays use Python numbering, Monday = 0. A window whose end is before its
    start runs overnight, and weekdays name the day it starts.
    """

    weekdays: frozenset[int]
    start: time
    end: time
    label: str = ""

    def contains(self, local: datetime) -> bool:
        t, day = local.time(), local.weekday()
        if self.start <= self.end:
            return day in self.weekdays and self.start <= t <= self.end
        return (day in self.weekdays and t >= self.start) or (
            (day - 1) % 7 in self.weekdays and t <= self.end
        )

@dataclass(frozen=True)
class OneTimeWindow:
    """A single expected visit, e.g. a contractor appointment."""

    start: datetime
    end: datetime
    label: str = ""

    def contains(self, local: datetime) -> bool:
        return self.start <= local <= self.end

@dataclass(frozen=True)
class Context:
    now: datetime
    set_point_f: float | None = None
    """Cooling set point, in Fahrenheit."""

    visitor_windows: Sequence[VisitorWindow] = ()
    timezone: str = "America/New_York"
    month: int | None = None
    southern_hemisphere: bool = False
    """Seasons flip south of the equator: summer_months are read six months later."""
    """Override for the season; defaults to the month of ``now`` in local time."""

    def __post_init__(self) -> None:
        _require_aware(self.now, "Context.now")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def local(self, at: datetime) -> datetime:
        return at.astimezone(self.tz)

    @property
    def current_month(self) -> int:
        return self.month or self.local(self.now).month

    def in_visitor_window(self, at: datetime) -> bool:
        local = self.local(at)
        return any(w.contains(local) for w in self.visitor_windows)

def _require_aware(at: datetime, what: str) -> None:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware, got {at!r}")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged

@dataclass(frozen=True)
class RulesConfig:
    summer_months: frozenset[int]
    vision_min_confidence: float
    sensor_max_gap: timedelta
    rules: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def defaults_mapping(cls) -> dict[str, Any]:
        text = resources.files("home_conditions.data").joinpath("rules.yaml").read_text()
        return yaml.safe_load(text)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> RulesConfig:
        unknown = set(data.get("rules", {})) - set(_REGISTRY)
        if unknown:
            raise ValueError(f"unknown rule ids in config: {sorted(unknown)}")
        return cls(
            summer_months=frozenset(data["summer_months"]),
            vision_min_confidence=float(data["vision_min_confidence"]),
            sensor_max_gap=timedelta(minutes=data["sensor_max_gap_minutes"]),
            rules=data["rules"],
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> RulesConfig:
        """Packaged defaults, with an optional YAML file merged over them."""
        data = cls.defaults_mapping()
        if path is not None:
            data = _deep_merge(data, yaml.safe_load(Path(path).read_text()) or {})
        return cls.from_mapping(data)

    def rule(self, rule_id: str) -> dict[str, Any]:
        return self.rules[rule_id]

    def severity(self, rule_id: str, key: str = "severity") -> Severity:
        return Severity.parse(self.rules[rule_id][key])

    def is_summer(self, ctx: Context) -> bool:
        """summer_months are Northern Hemisphere months; shifted six months for the south."""
        month = ctx.current_month
        if ctx.southern_hemisphere:
            month = (month + 5) % 12 + 1
        return month in self.summer_months

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_time(ctx: Context, at: datetime) -> str:
    """Owner-facing local time: abbreviated weekday, month, day, and clock."""
    local = ctx.local(at)
    hour = local.hour % 12 or 12
    return f"{local:%a %b} {local.day}, {hour}:{local:%M %p}"

def fmt_duration(span: timedelta) -> str:
    minutes = int(span.total_seconds() // 60)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} h")
    if minutes and not days:
        parts.append(f"{minutes} min")
    return " ".join(parts) or "under a minute"

class _Index:
    """Per-evaluation lookups shared by the rules."""

    def __init__(self, obs: Observations):
        self.obs = obs
        self.devices = {d.id: d for d in obs.devices}
        self.readings: dict[str, list[SensorReading]] = defaultdict(list)
        for r in sorted(obs.readings, key=lambda r: r.at):
            self.readings[r.device_id].append(r)
        self.sweeps: dict[str, list[Sweep]] = defaultdict(list)
        for s in sorted(obs.sweeps, key=lambda s: s.at):
            self.sweeps[s.device_id].append(s)

    def label(self, device_id: str) -> str:
        device = self.devices.get(device_id)
        return device.label if device else device_id

    def series(self, device_id: str, attr: str) -> list[tuple[datetime, Any]]:
        return [
            (r.at, getattr(r, attr))
            for r in self.readings[device_id]
            if getattr(r, attr) is not None
        ]

    def latest_sweeps(self) -> list[Sweep]:
        return [sweeps[-1] for sweeps in self.sweeps.values() if sweeps]

def _make(
    cfg: RulesConfig,
    rule_id: str,
    severity: Severity,
    detail: str,
    device_ids: Iterable[str] = (),
    *,
    started_at: datetime | None = None,
    ongoing: bool = True,
    category: str | None = None,
    evidence: dict[str, Any] | None = None,
    recommendation: str | None = None,
    specialist: str | None = None,
    specialist_set: bool = False,
) -> Finding:
    rule = cfg.rule(rule_id)
    return Finding(
        rule_id=rule_id,
        category=category or rule["category"],
        severity=severity,
        title=rule["title"],
        detail=detail,
        recommendation=recommendation if recommendation is not None else rule["recommendation"],
        specialist=specialist if specialist_set else rule.get("specialist"),
        device_ids=tuple(device_ids),
        started_at=started_at,
        ongoing=ongoing,
        evidence=evidence or {},
    )

def _trailing_streak(sweeps: Sequence[Sweep], hit: Callable[[Sweep], bool]) -> list[Sweep]:
    """The most recent consecutive sweeps for which ``hit`` is true, oldest first."""
    streak: list[Sweep] = []
    for sweep in reversed(sweeps):
        if not hit(sweep):
            break
        streak.append(sweep)
    return streak[::-1]

# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

RuleFn = Callable[[_Index, Context, RulesConfig], list[Finding]]
Interval = tuple[datetime, datetime | None]
"""(start, end); end None means still ongoing at Context.now."""

def active_water(ix: _Index, ctx: Context, cfg: RulesConfig) -> list[Finding]:
    severity = cfg.severity("active_water")
    findings = []
    for device_id in ix.readings:
        states = ix.series(device_id, "flood_wet")
        wet = [at for at, is_wet in states if is_wet]
        if not wet:
            continue
        still_wet = states[-1][1]
        tail = " It still reads wet." if still_wet else " It has since read dry."
        findings.append(
            _make(
                cfg,
                "active_water",
                severity,
                f"Flood sensor {ix.label(device_id)} reported water at "
                f"{fmt_time(ctx, wet[0])}.{tail}",
                [device_id],
                started_at=wet[0],
                ongoing=bool(still_wet),
                evidence={"source": "sensor", "wet_readings": len(wet)},
            )
        )
    for sweep in ix.latest_sweeps():
        hits = sweep.result.with_category("water", cfg.vision_min_confidence)
        if not hits:
            continue
        best = max(hits, key=lambda f: f.confidence)
        streak = _trailing_streak(
            ix.sweeps[sweep.device_id],
            lambda s: bool(s.result.with_category("water", cfg.vision_min_confidence)),
        )
        findings.append(
            _make(
                cfg,
                "active_water",
                severity,
                f"Camera {ix.label(sweep.device_id)} at {fmt_time(ctx, sweep.at)}: "
                f"{best.description} ({best.where}). Confidence {best.confidence:.0%}.",
                [sweep.device_id],
                # When the water first appeared, so repeat sweeps update one finding.
                started_at=streak[0].at,
                evidence={"source": "vision", "sweep_at": sweep.at.isoformat()},
            )
        )
    return findings

def _offline_intervals(ix: _Index) -> tuple[dict[str, list[Interval]], list[Interval]]:
    """Per-device offline intervals, and the intervals when every device was offline.

    Devices are assumed online until their first event says otherwise. An open
    interval (end None) is still ongoing at ctx.now.
    """
    device_ids = set(ix.devices) or {e.device_id for e in ix.obs.status_events}
    events = sorted(
        (e for e in ix.obs.status_events if e.device_id in device_ids), key=lambda e: e.at
    )
    per_device: dict[str, list[Interval]] = defaultdict(list)
    offline_since: dict[str, datetime] = {}
    all_offline: list[Interval] = []
    everything_down_since: datetime | None = None

    for event in events:
        if not event.online and event.device_id not in offline_since:
            offline_since[event.device_id] = event.at
        elif event.online and event.device_id in offline_since:
            per_device[event.device_id].append((offline_since.pop(event.device_id), event.at))

        if device_ids and len(offline_since) == len(device_ids):
            everything_down_since = everything_down_since or event.at
        elif everything_down_since is not None:
            all_offline.append((everything_down_since, event.at))
            everything_down_since = None

    for device_id, since in offline_since.items():
        per_device[device_id].append((since, None))
    if everything_down_since is not None:
        all_offline.append((everything_down_since, None))
    return per_device, all_offline

def outage(ix: _Index, ctx: Context, cfg: RulesConfig) -> list[Finding]:
    rule = cfg.rule("outage")
    minimum = timedelta(minutes=rule["all_offline_minutes"])
    long = timedelta(hours=rule["long_outage_hours"])
    _, all_offline = _offline_intervals(ix)
    count = len(ix.devices) or len({e.device_id for e in ix.obs.status_events})
    findings = []
    for start, end in all_offline:
        span = (end or ctx.now) - start
        if span < minimum:
            continue
        key = "severity_long_in_summer" if span > long and cfg.is_summer(ctx) else "severity"
        if end is None:
            state = f"and have been offline for {fmt_duration(span)}"
        else:
            state = f"and came back at {fmt_time(ctx, end)} after {fmt_duration(span)}"
        findings.append(
            _make(
                cfg,
                "outage",
                cfg.severity("outage", key),
                f"All {count} devices went offline at {fmt_time(ctx, start)} {state}. When "
                "every device drops at once, the usual cause is a power or internet outage "
                "at the house.",
                sorted(ix.devices) or (),
                started_at=start,
                ongoing=end is None,
                evidence={
                    "minutes": int(span.total_seconds() // 60),
                    # On reconnect the backend runs a full sweep against pre-outage baselines.
                    "sweep_on_reconnect": end is not None,
                },
            )
        )
    return findings

def freeze(ix: _Index, ctx: Context, cfg: RulesConfig) -> list[Finding]:
    below = cfg.rule("freeze")["below_f"]
    findings = []
    for device_id, readings in ix.readings.items():
        alerts = [r for r in readings if r.freeze_alert]
        cold = [r for r in readings if r.temperature_f is not None and r.temperature_f < below]
        if not alerts and not cold:
            continue
        if cold:
            lowest = min(cold, key=lambda r: r.temperature_f)
            detail = (
                f"Indoor temperature at {ix.label(device_id)} fell to "
                f"{lowest.temperature_f:.0f}F at {fmt_time(ctx, lowest.at)}, below the "
                f"{below}F threshold."
            )
        else:
            detail = (
                f"Freeze sensor {ix.label(device_id)} reported freezing conditions at "
                f"{fmt_time(ctx, alerts[0].at)}."
            )
        first = min(r.at for r in alerts + cold)
        findings.append(
            _make(cfg, "freeze", cfg.severity("freeze"), detail, [device_id], started_at=first)
        )
    return findings

_REGISTRY: dict[str, RuleFn] = {}

def register_rule(rule_id: str, fn: RuleFn) -> None:
    """Add or replace a rule. Another package uses this to install its own set."""
    _REGISTRY[rule_id] = fn

def registered_rule_ids() -> tuple[str, ...]:
    return tuple(_REGISTRY)


def clear_rules() -> None:
    """Remove every registered rule so a host package can install its own set."""
    _REGISTRY.clear()

def evaluate(obs: Observations, ctx: Context, config: RulesConfig | None = None) -> list[Finding]:
    """Run every enabled registered rule and return findings, most consequential first."""
    config = config or RulesConfig.load()
    for at in obs.timestamps():
        _require_aware(at, "observation timestamp")
    ix = _Index(obs)
    findings: list[Finding] = []
    for rule_id, fn in _REGISTRY.items():
        spec = config.rules.get(rule_id)
        if spec and spec.get("enabled", True):
            findings.extend(fn(ix, ctx, config))
    return rank_findings(findings)

register_rule("active_water", active_water)
register_rule("freeze", freeze)
register_rule("outage", outage)
