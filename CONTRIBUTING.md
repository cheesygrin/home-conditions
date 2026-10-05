# Contributing

home-conditions is a thin Apache-2.0 framework for home-monitoring apps. It is not published to PyPI.

## Setup

Python 3.12, via uv.

```bash
uv sync
uv run pytest
uv run ruff check .
```

## Add a rule

Register the function, then give it a block in your own thresholds file. `RulesConfig.load` merges that file over the sample defaults. A registered rule with no block is skipped. A block whose id was never registered is rejected.

```python
from home_conditions.rules import RulesConfig, evaluate, register_rule


def porch_light(ix, ctx, cfg):
    return []


register_rule("porch_light", porch_light)
config = RulesConfig.load("my_rules.yaml")
findings = evaluate(observations, context, config)
```

```yaml
rules:
  porch_light:
    enabled: true
    category: lighting
    severity: Info
    title: Porch light
    recommendation: Note the change and check the fixture on the next visit.
```

Titles and recommendations have to pass `home_conditions.language.lint`. Say "growth" or "discoloration", cite no code, and stay measured.

The sample numbers in `src/home_conditions/data/rules.yaml` are examples. Keep your tuned numbers in the host package's own YAML.

## Serial rules

`src/home_conditions/data/serial_rules.yaml` holds fictitious samples. Add a real rule only from that manufacturer's own public documentation, and put the citation in `source`.

## What not to commit

Secrets, `.env`, and a host app's tuned thresholds or private prompts.
