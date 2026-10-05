from dataclasses import dataclass

import pytest

from home_conditions.language import (
    LanguageError,
    LanguageRules,
    check,
    is_clean,
    lint,
    rank_findings,
)
from home_conditions.rules import RulesConfig
from home_conditions.severity import Severity


@pytest.mark.parametrize(
    "text",
    [
        "Mold on the drywall",
        "moldy smell at the closet",
        "Possible MOULD behind the sink",
        "mold-like staining",
        "mildew on the grout",
    ],
)
def test_banned_words_are_caught(text):
    issues = lint(text)
    assert [i.kind for i in issues] == ["banned_words"]
    assert "growth" in issues[0].suggestion


def test_trim_molding_is_allowed():
    assert is_clean("Crown molding is loose at the hall ceiling.")


@pytest.mark.parametrize(
    "text",
    [
        "Not to code per the IRC.",
        "This violates the Florida Building Code.",
        "See NEC requirements.",
        "Required by R314.3 for each bedroom.",
        "Refer to Section E3902 for GFCI locations.",
        "A code violation at the panel.",
        "§ 553.73 applies.",
    ],
)
def test_code_citations_are_caught(text):
    assert "code_citations" in {i.kind for i in lint(text)}


def test_appliance_error_code_is_not_a_citation():
    assert is_clean("The water heater display shows error code 4.")


@pytest.mark.parametrize(
    "text",
    [
        "A dangerous condition at the panel.",
        "Catastrophic water damage is likely.",
        "Water on the floor!",
        "The ceiling is ruined.",
        "Toxic growth in the attic.",
    ],
)
def test_alarmist_wording_is_caught(text):
    assert "alarmist" in {i.kind for i in lint(text)}


def test_measured_finding_text_is_clean():
    text = (
        "Reflective pooled liquid on the floor in front of the sink base. Have a licensed "
        "plumbing contractor evaluate the full water supply and drain system."
    )
    assert lint(text) == []


def test_issues_come_back_in_reading_order():
    issues = lint("Dangerous mold!")
    assert [i.match.lower() for i in issues] == ["dangerous", "mold", "!"]


def test_check_raises_with_every_issue():
    with pytest.raises(LanguageError) as err:
        check("Mold per code!")
    assert len(err.value.issues) == 3
    assert check("Discoloration at the ceiling.") == "Discoloration at the ceiling."


def test_every_packaged_rule_text_passes_the_linter():
    for rule_id, rule in RulesConfig.load().rules.items():
        for field in ("title", "recommendation"):
            assert lint(rule[field]) == [], f"{rule_id}.{field}"


def test_rules_load_from_a_custom_file(tmp_path):
    path = tmp_path / "language.yaml"
    path.write_text(
        "banned_words:\n  - pattern: '\\bflood\\b'\n    suggestion: Say water.\n"
        "consequence_order: [water]\n"
    )
    rules = LanguageRules.load(path)
    assert not is_clean("Flood in the garage", rules)
    assert is_clean("Mold in the garage", rules)  # the custom file replaces the defaults


@dataclass
class Item:
    name: str
    severity: Severity
    category: str


def test_rank_by_severity_then_consequence():
    items = [
        Item("packages", Severity.MONITOR, "package"),
        Item("outage", Severity.MONITOR, "outage"),
        Item("person", Severity.URGENT, "person"),
        Item("humidity", Severity.URGENT, "humidity"),
        Item("water", Severity.CRITICAL, "water"),
        Item("lighting", Severity.INFO, "benign"),
        Item("mystery", Severity.MONITOR, "not-a-category"),
    ]
    ranked = [i.name for i in rank_findings(items)]
    assert ranked == ["water", "humidity", "person", "outage", "packages", "mystery", "lighting"]
