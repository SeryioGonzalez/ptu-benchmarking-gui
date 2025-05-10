import logging
import os

from prometheus_client import REGISTRY, start_http_server
from prometheus_client.core import GaugeMetricFamily
from typing import Union

logger = logging.getLogger(__name__)
Number = Union[int, float]

PROMETHEUS_PORT = int(os.getenv("PROMETHEUS_PORT", 9100))

def start_exporter(stats_aggregator) -> None:
    """
    Expose `stats_aggregator.get_latest_metrics()` at /metrics.
    Call once, soon after you create the StatsAggregator instance.
    """

    class _StatsCollector:                    # ❶ pulls fresh dict each scrape
        def collect(self):
            for name, value in stats_aggregator.get_latest_metrics().items():
                if isinstance(value, (int, float)):       # skip timestamp str
                    g = GaugeMetricFamily(name, f"{name} (auto)", labels=[])
                    g.add_metric([], value)
                    yield g

    logger.info(f"Registering Prometheus collector for {stats_aggregator.__class__.__name__}")    
    REGISTRY.register(_StatsCollector())

    logger.info(f"Starting Prometheus exporter on port {PROMETHEUS_PORT}")
    start_http_server(PROMETHEUS_PORT)
    logger.info(f"Prometheus exporter up on :{PROMETHEUS_PORT}/metrics")

