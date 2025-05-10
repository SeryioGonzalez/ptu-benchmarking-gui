from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Dict, Iterable, Mapping, Tuple

from prometheus_client import Gauge, start_http_server

_LOG = logging.getLogger(__name__)
_METRICS: dict[str, Gauge] = {}
_METRIC_NAME_RE = re.compile(r"[^a-zA-Z0-9_:]")

###############################################################################
# Helpers
###############################################################################


def _normalise_key(key: str, prefix: str = "app") -> str:
    """
    Turn an arbitrary key path into a Prometheus-safe metric name.

    - everything to lower-case
    - non [a-zA-Z0-9_:] chars => '_'
    - prepend prefix
    """
    cleaned = _METRIC_NAME_RE.sub("_", key.lower())
    # Prometheus metric names may not start with a digit
    if cleaned and cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return f"{prefix}_{cleaned}"


def _flatten(d: Mapping[str, Any], path: Tuple[str, ...] = ()) -> Iterable[Tuple[str, Any]]:
    """
    Recursively flatten a mapping.

    {"a": {"b": 1}} -> [("a.b", 1)]
    """
    for k, v in d.items():
        new_path = (*path, k)
        if isinstance(v, Mapping):
            yield from _flatten(v, new_path)
        else:
            yield (".".join(new_path), v)


def _numeric(value: Any) -> float | None:
    """
    Convert *value* to a float if possible, otherwise return None.
    Accepts ints, floats, numeric strings; ignores "n/a", "", etc.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


###############################################################################
# Export logic
###############################################################################


def _export_once(aggregator: Any) -> None:
    """
    Pull one snapshot from *aggregator* and update all gauges.
    The aggregator must expose either:
        • .latest()   -> Mapping
        • .get_stats() -> Mapping
        • .stats       (property) -> Mapping
    First one that exists wins.
    """
    # 1. ----- obtain a stats snapshot --------------------------------------
    for attr in ("latest", "get_stats", "stats"):
        if hasattr(aggregator, attr):
            snap = getattr(aggregator, attr)
            snap = snap() if callable(snap) else snap
            break
    else:
        raise AttributeError(
            "statsaggregator exposes neither .latest(), .get_stats() nor .stats"
        )

    if not isinstance(snap, Mapping):
        _LOG.warning("Expected mapping from aggregator, got %r – skipping", type(snap))
        return

    # 2. ----- flatten & export ---------------------------------------------
    for key, val in _flatten(snap):
        num = _numeric(val)
        if num is None:
            continue  # skip non-numeric values, e.g. "n/a"
        mname = _normalise_key(key)

        gauge = _METRICS.get(mname)
        if gauge is None:
            gauge = Gauge(mname, f"Automatically generated metric for '{key}'")
            _METRICS[mname] = gauge
        gauge.set(num)


def _export_loop(aggregator: Any, interval: int) -> None:
    """Daemon thread – periodically calls `_export_once`."""
    _LOG.info("Prometheus exporter loop running every %ss", interval)
    while True:
        try:
            _export_once(aggregator)
        except Exception:  # noqa: BLE001
            _LOG.exception("Exporter failed – continuing")
        time.sleep(interval)


###############################################################################
# Public bootstrap
###############################################################################


def start_metrics_exporter(
    statsaggregator: Any,
    *,
    port: int = 8000,
    interval: int = 5,
    addr: str = "0.0.0.0",
) -> None:
    """
    Start the exporter.

    Parameters
    ----------
    statsaggregator
        Object providing stats (see `_export_once` for required interface).
    port
        TCP port on which to serve `/metrics`.
    interval
        Seconds between aggregator scrapes.
    addr
        Bind address (defaults to 0.0.0.0).
    """
    start_http_server(port, addr)
    _LOG.info("Prometheus /metrics endpoint listening on %s:%d", addr, port)

    t = threading.Thread(
        name="prometheus-exporter",
        target=_export_loop,
        args=(statsaggregator, interval),
        daemon=True,
    )
    t.start()