import io
import json

import jsonschema
import pytest
from PIL import Image, ImageDraw

from home_conditions.language import lint
from home_conditions.vision import (
    CATEGORIES,
    VisionContractError,
    build_compare_prompt,
    contract_schema,
    parse_vision_result,
    pixel_gate,
)

# The example from BLUEPRINT.md, verbatim.
BLUEPRINT_EXAMPLE = {
    "changed": True,
    "findings": [
        {
            "category": "water",
            "where": "floor in front of sink base, left third of frame",
            "description": "Reflective pooled liquid not present in baseline",
            "confidence": 0.86,
        }
    ],
    "benign_changes": ["lighting shift from window"],
}


def finding(**overrides):
    base = dict(BLUEPRINT_EXAMPLE["findings"][0])
    base.update(overrides)
    return base


def result(**overrides):
    base = {"changed": True, "findings": [finding()], "benign_changes": []}
    base.update(overrides)
    return base


# --- contract ---------------------------------------------------------------


def test_schema_is_valid_and_accepts_blueprint_example():
    schema = contract_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(BLUEPRINT_EXAMPLE, schema)
    assert tuple(schema["properties"]["findings"]["items"]["properties"]["category"]["enum"]) == (
        CATEGORIES
    )


def test_parse_blueprint_example():
    parsed = parse_vision_result(json.dumps(BLUEPRINT_EXAMPLE))
    assert parsed.changed
    assert parsed.findings[0].category == "water"
    assert parsed.findings[0].confidence == 0.86
    assert parsed.benign_changes == ("lighting shift from window",)
    assert parsed.to_dict() == BLUEPRINT_EXAMPLE


def test_parse_tolerates_a_json_fence():
    text = "```json\n" + json.dumps(BLUEPRINT_EXAMPLE) + "\n```"
    assert parse_vision_result(text).changed


def test_with_category_filters_by_confidence():
    parsed = parse_vision_result(result(findings=[finding(confidence=0.4)]))
    assert parsed.with_category("water") and not parsed.with_category("water", 0.6)


BAD_OUTPUTS = {
    "not json": "The floor looks wet.",
    "missing key": {"changed": True, "findings": []},
    "extra key": result(notes="hi"),
    "changed not bool": result(changed="yes"),
    "unknown category": result(findings=[finding(category="leak")]),
    "confidence too high": result(findings=[finding(confidence=1.2)]),
    "confidence is bool": result(findings=[finding(confidence=True)]),
    "confidence is text": result(findings=[finding(confidence="0.9")]),
    "empty where": result(findings=[finding(where="")]),
    "finding extra key": result(findings=[finding(severity="Critical")]),
    "benign not text": result(benign_changes=[3]),
    "unchanged with findings": result(changed=False),
}


@pytest.mark.parametrize("raw", BAD_OUTPUTS.values(), ids=BAD_OUTPUTS.keys())
def test_parse_rejects_contract_violations(raw):
    with pytest.raises(VisionContractError):
        parse_vision_result(raw if isinstance(raw, str) else json.dumps(raw))


@pytest.mark.parametrize(
    "raw",
    [v for k, v in BAD_OUTPUTS.items() if k not in {"not json", "unchanged with findings"}],
)
def test_json_schema_agrees_with_the_parser(raw):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, contract_schema())


def test_unchanged_with_only_lighting_is_allowed():
    raw = result(changed=False, findings=[finding(category="lighting")])
    assert not parse_vision_result(raw).changed


# --- prompts ----------------------------------------------------------------


def test_compare_prompt_carries_schema_view_and_lighting():
    prompt = build_compare_prompt("kitchen floor and sink base", "dusk", "Kitchen")
    assert '"growth_or_discoloration"' in prompt.system
    assert "kitchen floor and sink base" in prompt.user
    assert "dusk" in prompt.user
    assert "Image 1 is the BASELINE" in prompt.user


def test_results_from_before_outdoor_categories_still_parse():
    parsed = parse_vision_result(json.dumps(BLUEPRINT_EXAMPLE))
    assert parsed.findings[0].category == "water"
    assert "overgrowth" not in {f.category for f in parsed.findings}


def test_stain_parses_and_water_stays_standing_liquid():
    raw = result(
        findings=[
            finding(
                category="stain",
                where="ceiling above the hall",
                description="A tan mark covers 0.2 of the surface",
            )
        ]
    )
    parsed = parse_vision_result(raw)
    assert parsed.findings[0].category == "stain"
    prompt = build_compare_prompt("hall ceiling", "day")
    assert "standing, running, or dripping" in prompt.system
    assert "sagging" in prompt.system


def test_overgrowth_and_pool_water_parse():
    raw = result(
        findings=[
            finding(
                category="overgrowth",
                where="lawn and planters beside the walkway",
                description="planters along the walkway are fuller than the night baseline",
            ),
            finding(
                category="pool_water",
                where="pool surface",
                description="water is greener than the baseline, with debris on the surface",
            ),
        ]
    )
    parsed = parse_vision_result(raw)
    assert [f.category for f in parsed.findings] == ["overgrowth", "pool_water"]


def test_compare_prompt_follows_the_language_rules():
    prompt = build_compare_prompt("water heater closet", "night")
    assert not [i for i in lint(prompt.system + prompt.user) if i.kind == "banned_words"]


def test_compare_prompt_handles_blank_description():
    assert "not described" in build_compare_prompt("  ", "day").user


# --- pixel gate -------------------------------------------------------------


def scene(brightness=0, puddle=False, size=(320, 240)):
    """A fake kitchen frame: floor, cabinet, sink base. Optional puddle."""
    img = Image.new("L", size, 110 + brightness)
    draw = ImageDraw.Draw(img)
    draw.rectangle((40, 30, 280, 140), fill=70 + brightness)  # cabinet
    draw.rectangle((120, 60, 200, 140), fill=40 + brightness)  # sink base doors
    if puddle:
        draw.ellipse((90, 160, 230, 220), fill=210 + brightness)
    return img.convert("RGB")


def jpeg_bytes(img):
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def test_gate_stays_shut_for_identical_frames():
    gate = pixel_gate(scene(), scene())
    assert not gate.changed
    assert gate.changed_fraction == 0


def test_gate_ignores_a_uniform_lighting_shift():
    assert not pixel_gate(scene(), scene(brightness=30)).changed


def test_gate_ignores_jpeg_noise():
    assert not pixel_gate(jpeg_bytes(scene()), jpeg_bytes(scene())).changed


def test_gate_opens_for_a_puddle():
    gate = pixel_gate(scene(), scene(puddle=True))
    assert gate.changed
    assert gate.changed_fraction > 0.05


def test_gate_reads_files_and_bytes(tmp_path):
    path = tmp_path / "baseline.jpg"
    path.write_bytes(jpeg_bytes(scene()))
    assert pixel_gate(path, jpeg_bytes(scene(puddle=True))).changed
    assert pixel_gate(str(path), scene(puddle=True)).changed


def test_gate_without_normalization_sees_lighting_as_change():
    assert pixel_gate(scene(), scene(brightness=40), normalize_brightness=False).changed
