"""The vision contract, compare-prompt templates and a cheap pixel gate.

Flow for one camera on one sweep:
1. pixel_gate(baseline, current): if nothing changed, skip the model call.
2. build_compare_prompt(...): send baseline + current frames to a vision model.
3. parse_vision_result(model_output): validate against the contract.
4. Hand the VisionResult to the rules engine. Rules read only this shape.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageStat

CATEGORIES = (
    "water",
    "opening",
    "damage",
    "growth_or_discoloration",
    "person",
    "package",
    "debris",
    "overgrowth",
    "pool_water",
    "lighting",
    "other",
)


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


@cache
def contract_schema() -> dict[str, Any]:
    """The JSON Schema for a compare result (data/vision_contract.schema.json)."""
    text = (
        resources.files("home_conditions.data").joinpath("vision_contract.schema.json").read_text()
    )
    return json.loads(text)


@dataclass(frozen=True)
class VisionFinding:
    category: str
    where: str
    description: str
    confidence: float


@dataclass(frozen=True)
class VisionResult:
    changed: bool
    findings: tuple[VisionFinding, ...] = ()
    benign_changes: tuple[str, ...] = ()

    def with_category(self, category: str, min_confidence: float = 0.0) -> list[VisionFinding]:
        return [
            f for f in self.findings if f.category == category and f.confidence >= min_confidence
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "findings": [f.__dict__.copy() for f in self.findings],
            "benign_changes": list(self.benign_changes),
        }


UNCHANGED = VisionResult(changed=False)
"""What the pixel gate reports when it skips the model call."""


class VisionContractError(ValueError):
    """Model output didn't match the contract. Retry the call or log it; never guess."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VisionContractError(message)


def parse_vision_result(raw: str | bytes | dict[str, Any]) -> VisionResult:
    """Validate model output against the contract and return a VisionResult.

    Accepts the JSON text straight from the model. A ```json fence around it is
    tolerated, because models add one despite instructions. Anything else that
    doesn't match the schema raises VisionContractError.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else ""
            text = text.rsplit("```", 1)[0]
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise VisionContractError(f"not valid JSON: {exc}") from None
    else:
        data = raw

    _require(isinstance(data, dict), "top level must be an object")
    expected = {"changed", "findings", "benign_changes"}
    _require(set(data) == expected, f"keys must be exactly {sorted(expected)}, got {sorted(data)}")
    _require(isinstance(data["changed"], bool), "changed must be true or false")
    _require(isinstance(data["findings"], list), "findings must be a list")
    _require(isinstance(data["benign_changes"], list), "benign_changes must be a list")

    findings = []
    for i, item in enumerate(data["findings"]):
        where = f"findings[{i}]"
        _require(isinstance(item, dict), f"{where} must be an object")
        keys = {"category", "where", "description", "confidence"}
        _require(set(item) == keys, f"{where} keys must be exactly {sorted(keys)}")
        _require(item["category"] in CATEGORIES, f"{where}.category {item['category']!r} unknown")
        for field in ("where", "description"):
            value = item[field]
            _require(isinstance(value, str) and value.strip(), f"{where}.{field} must be text")
        confidence = item["confidence"]
        _require(
            isinstance(confidence, int | float) and not isinstance(confidence, bool),
            f"{where}.confidence must be a number",
        )
        _require(0.0 <= confidence <= 1.0, f"{where}.confidence must be between 0 and 1")
        findings.append(
            VisionFinding(item["category"], item["where"], item["description"], float(confidence))
        )

    for i, item in enumerate(data["benign_changes"]):
        _require(isinstance(item, str) and item.strip(), f"benign_changes[{i}] must be text")

    substantive = [f for f in findings if f.category != "lighting"]
    _require(
        data["changed"] or not substantive,
        "changed is false but findings other than lighting were listed",
    )
    return VisionResult(data["changed"], tuple(findings), tuple(data["benign_changes"]))


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

COMPARE_SYSTEM_PROMPT = """\
You compare two pictures of the same view. Picture 1 is the BASELINE. \
Picture 2 is the CURRENT picture.
Report what differs in the CURRENT picture that could affect the building \
or the things kept there.

Use the categories named in the schema. Describe only what is visible. Do not guess causes.
Keep the wording measured and factual. For biological-looking staining, \
use the words "growth" or "discoloration".
Ordinary differences in daylight or exposure go in benign_changes, not findings.
If nothing but those ordinary differences exist, return changed false and an empty findings list.

Respond with one JSON object and nothing else, matching this JSON Schema:
{schema}
"""

COMPARE_USER_PROMPT = """\
Camera: {camera_label}
What this view shows: {view_description}
Lighting: {lighting_bucket}

Image 1 is the BASELINE. Image 2 is the CURRENT picture. Compare them and respond with \
the JSON object only.
"""


@dataclass(frozen=True)
class ComparePrompt:
    system: str
    user: str


def build_compare_prompt(
    view_description: str, lighting_bucket: str, camera_label: str = "camera"
) -> ComparePrompt:
    """Example prompt for one baseline compare. Send the baseline image first, then the current."""
    schema = json.dumps(contract_schema(), indent=None, separators=(",", ":"))
    return ComparePrompt(
        system=COMPARE_SYSTEM_PROMPT.format(schema=schema),
        user=COMPARE_USER_PROMPT.format(
            camera_label=camera_label.strip() or "camera",
            view_description=view_description.strip() or "not described",
            lighting_bucket=lighting_bucket,
        ),
    )


# ---------------------------------------------------------------------------
# Pixel gate
# ---------------------------------------------------------------------------

ImageInput = str | Path | bytes | Image.Image


@dataclass(frozen=True)
class GateResult:
    changed: bool
    """True when the frames differ enough to be worth a model call."""

    changed_fraction: float
    """Share of downscaled pixels that moved more than the pixel threshold."""

    mean_abs_diff: float
    """Average absolute difference, 0-255, after brightness normalisation."""


def _load_gray(image: ImageInput, size: int) -> Image.Image:
    if isinstance(image, bytes):
        image = Image.open(io.BytesIO(image))
    elif isinstance(image, str | Path):
        image = Image.open(image)
    # Downscaling with a box filter averages neighbourhoods, which also smooths
    # compression noise and small sensor jitter.
    return image.convert("L").resize((size, size), Image.Resampling.BOX)


def pixel_gate(
    baseline: ImageInput,
    current: ImageInput,
    *,
    size: int = 64,
    pixel_threshold: int = 24,
    min_changed_fraction: float = 0.01,
    normalize_brightness: bool = True,
) -> GateResult:
    """Cheap check before a vision call: did anything in the frame actually change?

    Both frames are shrunk to size x size grayscale. With normalize_brightness,
    each frame's mean brightness is removed first, so a uniform exposure or
    daylight shift does not count as change. A pixel counts as changed when it
    moved by more than pixel_threshold (0-255). The gate opens when at least
    min_changed_fraction of pixels changed.

    Defaults lean toward calling the model: a missed leak costs far more than a
    wasted call.
    """
    a = _load_gray(baseline, size)
    b = _load_gray(current, size)
    if normalize_brightness:
        shift = round(ImageStat.Stat(a).mean[0] - ImageStat.Stat(b).mean[0])
        # Image.point maps every pixel; clamp so the shifted value stays in range.
        b = b.point(lambda v: max(0, min(255, v + shift)))
    diff = ImageChops.difference(a, b)
    histogram = diff.histogram()
    total = size * size
    changed_pixels = sum(histogram[pixel_threshold + 1 :])
    mean_abs = sum(level * count for level, count in enumerate(histogram)) / total
    fraction = changed_pixels / total
    return GateResult(fraction >= min_changed_fraction, fraction, mean_abs)
