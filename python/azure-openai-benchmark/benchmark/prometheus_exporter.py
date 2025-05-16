import logging, os
from prometheus_client import REGISTRY, start_http_server
from prometheus_client.core import GaugeMetricFamily
from typing import Union, Callable

logger = logging.getLogger(__name__)
Number = Union[int, float]
PROMETHEUS_PORT = int(os.getenv("BENCHMARK_TOOL_PROMETHEUS_METRIC_EXPORT_PORT", 9100))

# 👉 the current stats provider (callable returning a dict) can be hot-swapped
_current_metrics_provider: Callable[[], dict] | None = None
_exporter_started = False


class _StatsCollector:
    def collect(self):
        if _current_metrics_provider is None:
            return
        label = _current_metrics_provider()['label']
        for name, value in _current_metrics_provider().items():
            if isinstance(value, (int, float)):
                g = GaugeMetricFamily(name, f"{name} (auto)", labels=["label"])
                g.add_metric([label], value)        # generic label
                yield g


def set_metrics_provider(provider: Callable[[], dict] | None):
    """
    Point the collector at a new stats provider (or None for idle state).
    """
    global _current_metrics_provider
    _current_metrics_provider = provider


def start_exporter() -> None:
    """
    Fire up the exporter once.  Subsequent calls are ignored.
    """
    global _exporter_started
    if _exporter_started:
        logger.debug("Prometheus exporter already running")
        return

    REGISTRY.register(_StatsCollector())
    start_http_server(PROMETHEUS_PORT)
    _exporter_started = True
    logger.info(f"Prometheus exporter up on :{PROMETHEUS_PORT}/metrics")