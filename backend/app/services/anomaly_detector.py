"""Rules-based anomaly detection over a window of logs.

MVP heuristics (Plan §6.2):
- Spike in error frequency
- Repeated identical errors
- Latency threshold breaches (if message encodes latency_ms)
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Iterable, List, Sequence

from app.models.log import Log

_ERROR_LEVELS = {"error", "critical", "fatal"}
_LATENCY_RE = re.compile(r"latency[_\s-]*ms?\s*[=:]\s*(\d+(?:\.\d+)?)", re.IGNORECASE)


@dataclass
class Anomaly:
    kind: str
    service: str
    severity: str
    summary: str
    evidence_log_ids: List[int] = field(default_factory=list)
    score: float = 0.0


@dataclass
class DetectorConfig:
    error_spike_threshold: int = 5  # errors per window to trigger
    window: timedelta = timedelta(minutes=5)
    repeated_error_threshold: int = 3
    latency_threshold_ms: float = 1000.0


def detect_anomalies(
    logs: Sequence[Log],
    config: DetectorConfig | None = None,
) -> List[Anomaly]:
    cfg = config or DetectorConfig()
    anomalies: List[Anomaly] = []

    by_service: dict[str, List[Log]] = defaultdict(list)
    for log in logs:
        by_service[log.service_name].append(log)

    for service, svc_logs in by_service.items():
        svc_logs = sorted(svc_logs, key=lambda l: l.timestamp)
        anomalies.extend(_detect_error_spike(service, svc_logs, cfg))
        anomalies.extend(_detect_repeated_errors(service, svc_logs, cfg))
        anomalies.extend(_detect_latency_breach(service, svc_logs, cfg))

    return anomalies


def _detect_error_spike(
    service: str, svc_logs: List[Log], cfg: DetectorConfig
) -> Iterable[Anomaly]:
    errors = [l for l in svc_logs if (l.severity or "").lower() in _ERROR_LEVELS]
    if not errors:
        return []

    # Sliding window count.
    i = 0
    for j in range(len(errors)):
        while errors[j].timestamp - errors[i].timestamp > cfg.window:
            i += 1
        count = j - i + 1
        if count >= cfg.error_spike_threshold:
            return [
                Anomaly(
                    kind="error_spike",
                    service=service,
                    severity="high",
                    summary=(
                        f"{count} errors in {service} within "
                        f"{int(cfg.window.total_seconds() / 60)} min window"
                    ),
                    evidence_log_ids=[l.id for l in errors[i : j + 1] if l.id is not None],
                    score=min(1.0, count / (cfg.error_spike_threshold * 2)),
                )
            ]
    return []


def _detect_repeated_errors(
    service: str, svc_logs: List[Log], cfg: DetectorConfig
) -> Iterable[Anomaly]:
    errors = [l for l in svc_logs if (l.severity or "").lower() in _ERROR_LEVELS]
    if not errors:
        return []

    counter = Counter((l.message.strip()[:200] for l in errors))
    out: List[Anomaly] = []
    for message, count in counter.items():
        if count >= cfg.repeated_error_threshold:
            ids = [l.id for l in errors if l.message.strip().startswith(message[:50]) and l.id is not None]
            out.append(
                Anomaly(
                    kind="repeated_error",
                    service=service,
                    severity="medium",
                    summary=f'"{message[:80]}..." repeated {count}x in {service}',
                    evidence_log_ids=ids[:20],
                    score=min(1.0, count / (cfg.repeated_error_threshold * 3)),
                )
            )
    return out


def _detect_latency_breach(
    service: str, svc_logs: List[Log], cfg: DetectorConfig
) -> Iterable[Anomaly]:
    breaches: List[Log] = []
    for log in svc_logs:
        match = _LATENCY_RE.search(log.message or "")
        if match and float(match.group(1)) > cfg.latency_threshold_ms:
            breaches.append(log)

    if len(breaches) < 3:
        return []

    return [
        Anomaly(
            kind="latency_breach",
            service=service,
            severity="medium",
            summary=(
                f"{len(breaches)} latency samples exceeded "
                f"{cfg.latency_threshold_ms:.0f}ms in {service}"
            ),
            evidence_log_ids=[l.id for l in breaches[:20] if l.id is not None],
            score=min(1.0, len(breaches) / 20.0),
        )
    ]


__all__ = ["Anomaly", "DetectorConfig", "detect_anomalies"]
