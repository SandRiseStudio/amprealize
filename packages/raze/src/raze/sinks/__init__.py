"""Raze sink implementations for log storage backends.

Available sinks:
- InMemorySink: For testing and development
- FileSink: JSONL file storage
- TimescaleDBSink: TimescaleDB hypertable storage
- KafkaSink: Kafka topic streaming
- SlackSink: Slack webhook alerting
"""

from raze.sinks.base import RazeSink
from raze.sinks.memory import InMemorySink
from raze.sinks.file import FileSink

__all__ = [
    "RazeSink",
    "InMemorySink",
    "FileSink",
]

# Conditional imports for optional dependencies
try:
    from raze.sinks.timescale import TimescaleDBSink
    __all__.append("TimescaleDBSink")
except ImportError:
    pass

try:
    from raze.sinks.kafka import KafkaSink
    __all__.append("KafkaSink")
except ImportError:
    pass

try:
    from raze.sinks.slack import SlackSink, SlackAlertRule, create_cost_alert_sink
    __all__.extend(["SlackSink", "SlackAlertRule", "create_cost_alert_sink"])
except ImportError:
    pass
