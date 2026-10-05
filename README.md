# home-conditions

A thin building-science framework for home-monitoring apps. Apache-2.0. Not published to PyPI.

It loads thresholds from YAML, runs the rules you register, and returns findings ranked by consequence. Three sample rules ship with sample numbers so you can try the shape. A host package registers its own rules and its own thresholds file.

## Install

Python 3.12 or newer. Dependencies: PyYAML and Pillow.

```bash
uv sync
```

From a built wheel:

```bash
uv build
uv venv /tmp/hc-wheel
uv pip install --python /tmp/hc-wheel/bin/python dist/home_conditions-0.1.0-py3-none-any.whl
```

Pinned from GitHub:

```bash
uv add "home-conditions @ git+https://github.com/cheesygrin/home-conditions.git@v0.1.0"
```

## Quick start

```python
from datetime import UTC, datetime

from home_conditions.rules import Context, Observations, SensorReading, evaluate

now = datetime.now(UTC)
findings = evaluate(
    Observations(readings=[SensorReading(now, "flood-1", flood_wet=True)]),
    Context(now=now),
)
for finding in findings:
    print(finding.severity.label, finding.title)
    print(" ", finding.detail)
```

That uses the sample thresholds (a wet flood sensor is Critical). Load your own file over them:

```python
from home_conditions.rules import RulesConfig, evaluate

findings = evaluate(observations, context, RulesConfig.load("my_rules.yaml"))
```

## Modules

| Module | Job |
| --- | --- |
| `rules` | Registry, YAML loader, evaluator, and sample rules for active water, freeze, and outage |
| `severity` | Critical / Urgent / Monitor / Info, and the delivery policy for each |
| `vision` | JSON Schema for a compare result, a parser, a pixel gate, and a generic example prompt |
| `language` | Linter for report language, and the consequence sort |
| `psychrometrics` | Dew point, humidity trends, sustained runs that respect gaps in the series |
| `units` | Fahrenheit or Celsius at the edge, and regional storm names |
| `appliances` | Expected-life table and sample serial-decoding rules |
| `synthetic` | Deterministic fixtures: a 6-hour cooling curve, a 20-minute outage, a 48-hour humidity soak |

## Sample rules

Numbers below are the packaged examples in `src/home_conditions/data/rules.yaml`. Replace them.

| Rule | Sample trigger | Sample severity |
| --- | --- | --- |
| Active water | Flood sensor wet, or water in a camera frame | Critical |
| Freeze | Freeze alert, or indoor temperature under 32F | Urgent |
| Outage | Every device offline for 5 minutes | Monitor; Urgent after 8 hours in summer |

Summer in the sample file is June, July, and August. `Context.southern_hemisphere` shifts those months by six.

## Register a rule

```python
from home_conditions.rules import register_rule

def porch_light(ix, ctx, cfg):
    return []

register_rule("porch_light", porch_light)
```

`evaluate` runs a registered rule only when your YAML has a block for that id. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Severity and delivery

| Severity | Meaning | Delivery |
| --- | --- | --- |
| Critical | Damage happening now | SMS and email immediately, dispatch button |
| Urgent | Damage likely within 48 hours | SMS within the hour |
| Monitor | Could become a problem | Weekly report |
| Info | A normal change | Logged only |

## Vision contract

A camera compare returns this shape. The schema is `src/home_conditions/data/vision_contract.schema.json`.

```json
{
  "changed": true,
  "findings": [
    {
      "category": "water",
      "where": "floor in front of sink base, left third of frame",
      "description": "Reflective pooled liquid not present in baseline",
      "confidence": 0.86
    }
  ],
  "benign_changes": ["lighting shift from window"]
}
```

```python
from home_conditions.vision import build_compare_prompt, parse_vision_result, pixel_gate

if pixel_gate(baseline_jpeg, current_jpeg).changed:
    prompt = build_compare_prompt("kitchen floor and sink base", "day", "Kitchen")
    result = parse_vision_result(model_text)
```

`build_compare_prompt` is a generic example. A host package can send its own prompt and still parse with `parse_vision_result`.

## Language

Reports use "growth" or "discoloration", cite no code, and stay measured. `language.check` raises unless the text is clean. Word lists live in `src/home_conditions/data/language.yaml`.

## Appliances

`assess_age("water_heater_tank_gas", year, 3)` compares a manufacture year with the expected-life table. `decode_serial(serial, brand)` returns candidate dates and a confidence score. The serial rules in the package are fictitious samples.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
```

## License

Apache-2.0. See [LICENSE](LICENSE).
