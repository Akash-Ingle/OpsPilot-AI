"""Prometheus metrics for OpsPilot.

A small, honest set of application counters exposed at ``GET /metrics`` (app
root) alongside the default process metrics. Scrape with Prometheus/Grafana.

Counters are incremented from the hot paths (ingestion, analysis, incident
creation). Importing this module is side-effect-free beyond registering the
metrics on the default registry.
"""

from __future__ import annotations

from prometheus_client import Counter

LOGS_INGESTED_TOTAL = Counter(
    "opspilot_logs_ingested_total",
    "Total log lines accepted via the /ingest endpoint.",
)

INCIDENTS_OPENED_TOTAL = Counter(
    "opspilot_incidents_opened_total",
    "Total incidents opened (by the watcher or an explicit /analyze call).",
    ["source"],  # "watcher" | "analyze"
)

ANALYSES_TOTAL = Counter(
    "opspilot_analyses_total",
    "Total agent analyses run.",
    ["served_from_cache"],  # "true" | "false"
)


def record_analysis(served_from_cache: bool) -> None:
    ANALYSES_TOTAL.labels(served_from_cache=str(served_from_cache).lower()).inc()


def record_incident(source: str) -> None:
    INCIDENTS_OPENED_TOTAL.labels(source=source).inc()


__all__ = [
    "LOGS_INGESTED_TOTAL",
    "INCIDENTS_OPENED_TOTAL",
    "ANALYSES_TOTAL",
    "record_analysis",
    "record_incident",
]
