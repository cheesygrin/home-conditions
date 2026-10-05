"""home-conditions: a thin building-science framework for home-monitoring apps.

Modules:
    psychrometrics  dew point, humidity trends, sustained-threshold detection
    rules           rule format, registry, evaluator, and three sample rules
    severity        Critical / Urgent / Monitor / Info and delivery policy
    vision          vision contract, parser, pixel gate, example compare prompt
    language        inspection-language linter and consequence ranking
    appliances      expected-life table and sample serial-decoding rules
    synthetic       deterministic sensor fixtures for tests and labeled demos
    units           display units and regional storm names
"""

from home_conditions.findings import Finding
from home_conditions.severity import Severity

__version__ = "0.1.0"

__all__ = ["Finding", "Severity", "__version__"]
