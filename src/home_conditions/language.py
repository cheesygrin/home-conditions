"""Inspection-language linter and consequence ranking.

House rules for every report and alert:
- Never the word for fungal growth that owners panic about; use "growth" or
  "discoloration".
- No code citations.
- Measured, non-alarmist tone.
- Findings ranked by consequence.

The word lists live in data/language.yaml so they can be edited without code.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any, Protocol

import yaml

from home_conditions.severity import Severity

KINDS = ("banned_words", "code_citations", "alarmist")


@dataclass(frozen=True)
class LintIssue:
    kind: str
    """One of "banned_words", "code_citations", "alarmist"."""

    match: str
    start: int
    end: int
    suggestion: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.match!r} at {self.start}. {self.suggestion}"


@dataclass(frozen=True)
class _Rule:
    kind: str
    regex: re.Pattern[str]
    suggestion: str


@dataclass(frozen=True)
class LanguageRules:
    rules: tuple[_Rule, ...]
    consequence_order: tuple[str, ...]

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> LanguageRules:
        rules = []
        for kind in KINDS:
            for entry in data.get(kind) or []:
                regex = re.compile(entry["pattern"], re.IGNORECASE)
                rules.append(_Rule(kind, regex, entry["suggestion"]))
        return cls(tuple(rules), tuple(data.get("consequence_order") or ()))

    @classmethod
    def load(cls, path: str | Path | None = None) -> LanguageRules:
        """Load from a YAML file, or the packaged defaults when path is None."""
        if path is None:
            text = resources.files("home_conditions.data").joinpath("language.yaml").read_text()
        else:
            text = Path(path).read_text()
        return cls.from_mapping(yaml.safe_load(text))


@cache
def default_rules() -> LanguageRules:
    return LanguageRules.load()


def lint(text: str, rules: LanguageRules | None = None) -> list[LintIssue]:
    """Every rule violation in ``text``, in reading order."""
    rules = rules or default_rules()
    issues = [
        LintIssue(rule.kind, m.group(0), m.start(), m.end(), rule.suggestion)
        for rule in rules.rules
        for m in rule.regex.finditer(text)
    ]
    return sorted(issues, key=lambda i: (i.start, i.kind))


def is_clean(text: str, rules: LanguageRules | None = None) -> bool:
    return not lint(text, rules)


class LanguageError(ValueError):
    def __init__(self, issues: Sequence[LintIssue]):
        self.issues = list(issues)
        super().__init__("; ".join(str(i) for i in issues))


def check(text: str, rules: LanguageRules | None = None) -> str:
    """Return ``text`` unchanged if clean; raise LanguageError listing every issue if not.

    Use this as the last step before anything is sent to an owner or vendor.
    """
    issues = lint(text, rules)
    if issues:
        raise LanguageError(issues)
    return text


class _Rankable(Protocol):
    @property
    def severity(self) -> Severity: ...
    @property
    def category(self) -> str: ...


def consequence_key(item: _Rankable, rules: LanguageRules | None = None) -> tuple[int, int]:
    """Sort key: higher severity first, then the category's place in consequence_order."""
    order = (rules or default_rules()).consequence_order
    try:
        place = order.index(item.category)
    except ValueError:
        place = len(order)
    return (-int(item.severity), place)


def rank_findings[R: _Rankable](items: Iterable[R], rules: LanguageRules | None = None) -> list[R]:
    """Most consequential first. Stable, so equal items keep their input order."""
    rules = rules or default_rules()
    return sorted(items, key=lambda item: consequence_key(item, rules))
