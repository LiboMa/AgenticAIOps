"""Alert parsers for monitoring systems that send to Slack channels.

Each parser implements AlertParser ABC: can_parse() + parse().
"""

from .base import AlertParser
from .cloudwatch import CloudWatchAlertParser
from .datadog import DatadogAlertParser
from .pagerduty import PagerDutyAlertParser
from .grafana import GrafanaAlertParser
from .generic import GenericAlertParser

# Priority-ordered: specific parsers first, generic last
ALL_PARSERS: list[AlertParser] = [
    CloudWatchAlertParser(),
    DatadogAlertParser(),
    PagerDutyAlertParser(),
    GrafanaAlertParser(),
    GenericAlertParser(),  # LLM-assisted fallback — always last
]

__all__ = [
    "AlertParser",
    "CloudWatchAlertParser",
    "DatadogAlertParser",
    "PagerDutyAlertParser",
    "GrafanaAlertParser",
    "GenericAlertParser",
    "ALL_PARSERS",
]
