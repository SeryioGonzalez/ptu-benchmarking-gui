"""
Exports StatsAggregator's gauges via Prometheus.

Importing this module has NO side-effects; call `start_exporter()` once near
program start-up (e.g. right after you create StatsAggregator).
"""

from __future__ import annotations
from typing import TYPE_CHECKING
from prometheus_client import Gauge, CollectorRegistry, start_http_server

if TYPE_CHECKING:                       # avoid circular import at runtime
    from .stats_aggregator import StatsAggregator

_PORT_DEFAULT = 9000
_registry: CollectorRegistry | None = None
_started: bool = False


def _gauge(name: str, description: str, value_fn):
    """
    Helper that registers a Gauge whose value is taken from `value_fn`
    every time Prometheus scrapes /metrics.
    """
    return Gauge(
        name,
        description,
        registry=_registry,
        # ValueFuncGauge is created under the hood when 'callback' is given
        # (see prometheus_client docs >= 0.20.0)
        labelnames=(),
        unit="",
        callback=value_fn,
    )


def start_exporter(stats: "StatsAggregator", port: int | None = None) -> None:
    """
    Idempotent initialiser – safe to call multiple times; only the first call
    does any work.
    """
    global _registry, _started
    if _started:         # already running
        return

    _registry = CollectorRegistry(auto_describe=True)

    # -----------------------------------------------------------------
    # Create one Gauge per *public* attribute that StatsAggregator marks
    # as exportable.  We use the convention: every attr in
    # `stats.prometheus_gauges` is a (metric_name, help_text) tuple.
    # -----------------------------------------------------------------
    for attr_name, (metric_name, help_text) in stats.prometheus_gauges.items():

        # Freeze `attr_name` in a new scope so every lambda has its own copy
        def _make_value_fn(an=attr_name):
            return lambda: getattr(stats, an)

        _gauge(metric_name, help_text, _make_value_fn())

    # finally expose /metrics
    start_http_server(port or _PORT_DEFAULT, registry=_registry)
    _started = True