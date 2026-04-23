"""Synthetic DevOps log generator (Plan §9).

Produces realistic-looking log streams for three failure scenarios, returned
in the structured shape that matches the `Log` ORM model:

- database_failure - connection timeouts + cascading 5xx
- memory_leak      - gradual heap growth + GC warnings + OOM
- latency_spike    - latency ramp with request timeouts at the peak

Each generator is deterministic when seeded and returns a list of `LogCreate`
schemas (fields: timestamp, service_name, severity, message) ready to be
passed to `Log(**entry.model_dump())` or seeded via the `/simulate` API route.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from app.schemas.log import LogCreate


# ---------------------------------------------------------------------------
# Scenario metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioMeta:
    name: str
    description: str
    default_duration_min: int
    default_service: str


SCENARIO_META: Dict[str, ScenarioMeta] = {
    "database_failure": ScenarioMeta(
        name="database_failure",
        description="Primary DB becomes unreachable; api-gateway and orders-svc log cascading timeouts and 5xx.",
        default_duration_min=10,
        default_service="orders-svc",
    ),
    "memory_leak": ScenarioMeta(
        name="memory_leak",
        description="inventory-svc heap grows until GC thrash and OOMError.",
        default_duration_min=30,
        default_service="inventory-svc",
    ),
    "latency_spike": ScenarioMeta(
        name="latency_spike",
        description="checkout-svc p99 latency climbs from ~80ms to >2000ms with upstream timeouts.",
        default_duration_min=15,
        default_service="checkout-svc",
    ),
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _rng(seed: Optional[int]) -> random.Random:
    return random.Random(seed) if seed is not None else random.Random()


def _ts_range(
    start: Optional[datetime],
    duration: timedelta,
) -> tuple[datetime, datetime]:
    end = (start or datetime.now(timezone.utc))
    end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
    start = end - duration
    return start, end


def _mk(ts: datetime, service: str, severity: str, message: str) -> LogCreate:
    return LogCreate(
        timestamp=ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc),
        service_name=service,
        severity=severity.lower(),
        message=message,
    )


def _background_info(
    rng: random.Random, service: str, ts: datetime
) -> LogCreate:
    """Produce a benign INFO log to pad the stream."""
    templates = [
        "handled GET /health in {latency}ms",
        "completed POST /events id={req_id} status=200",
        "scheduled job=nightly-report next_run=tomorrow",
        "cache hit rate={rate:.2f} for key_prefix=user:",
        "metrics flushed count={count}",
    ]
    t = rng.choice(templates)
    msg = t.format(
        latency=rng.randint(5, 60),
        req_id=f"r_{rng.randint(100000, 999999)}",
        rate=rng.uniform(0.7, 0.99),
        count=rng.randint(10, 400),
    )
    return _mk(ts, service, "info", msg)


# ---------------------------------------------------------------------------
# Scenario 1: Database failure
# ---------------------------------------------------------------------------


def simulate_database_failure(
    *,
    start: Optional[datetime] = None,
    duration: Optional[timedelta] = None,
    seed: Optional[int] = None,
    service: str = "orders-svc",
    upstream: str = "api-gateway",
) -> List[LogCreate]:
    """Connection timeouts against db-primary, cascading into api-gateway 5xx."""
    rng = _rng(seed)
    duration = duration or timedelta(minutes=SCENARIO_META["database_failure"].default_duration_min)
    t_start, t_end = _ts_range(start, duration)

    logs: List[LogCreate] = []

    # Phase 1 (0-30%): normal traffic on both services.
    normal_end = t_start + duration * 0.3
    t = t_start
    while t < normal_end:
        logs.append(_background_info(rng, service, t))
        logs.append(_background_info(rng, upstream, t + timedelta(seconds=rng.uniform(0.1, 0.8))))
        t += timedelta(seconds=rng.uniform(5, 15))

    # Phase 2 (30-60%): first db timeouts appear intermittently.
    rising_end = t_start + duration * 0.6
    while t < rising_end:
        if rng.random() < 0.5:
            logs.append(
                _mk(
                    t,
                    service,
                    "error",
                    f"connection timeout to db-primary after {rng.randint(4500, 5500)}ms "
                    f"pool=orders-pool waiting={rng.randint(5, 15)}",
                )
            )
        else:
            logs.append(_background_info(rng, service, t))
        t += timedelta(seconds=rng.uniform(3, 10))

    # Phase 3 (60-100%): sustained failure + cascading upstream 5xx.
    error_templates_db = [
        "connection timeout to db-primary after {ms}ms pool=orders-pool waiting={w}",
        "FATAL: connection pool exhausted (size=20 in_use=20) queue_depth={q}",
        "db query failed: SELECT orders.* - timeout exceeded (query_id={qid})",
        "circuit breaker opened for db-primary trips={trips} cooldown=30s",
    ]
    error_templates_upstream = [
        "upstream 503 from {svc} request_id={rid} path=/orders/{oid}",
        "request failed service={svc} code=UPSTREAM_TIMEOUT elapsed_ms={ms}",
    ]

    while t < t_end:
        if rng.random() < 0.75:
            tpl = rng.choice(error_templates_db)
            logs.append(
                _mk(
                    t,
                    service,
                    "critical" if "FATAL" in tpl else "error",
                    tpl.format(
                        ms=rng.randint(4800, 6000),
                        w=rng.randint(8, 30),
                        q=rng.randint(40, 120),
                        qid=f"q_{rng.randint(10000, 99999)}",
                        trips=rng.randint(3, 12),
                    ),
                )
            )
        if rng.random() < 0.5:
            tpl = rng.choice(error_templates_upstream)
            logs.append(
                _mk(
                    t + timedelta(milliseconds=rng.randint(50, 400)),
                    upstream,
                    "error",
                    tpl.format(
                        svc=service,
                        rid=f"rid_{rng.randint(100000, 999999)}",
                        oid=rng.randint(1000, 9999),
                        ms=rng.randint(5000, 8000),
                    ),
                )
            )
        t += timedelta(seconds=rng.uniform(2, 6))

    logs.sort(key=lambda l: l.timestamp)
    return logs


# ---------------------------------------------------------------------------
# Scenario 2: Memory leak
# ---------------------------------------------------------------------------


def simulate_memory_leak(
    *,
    start: Optional[datetime] = None,
    duration: Optional[timedelta] = None,
    seed: Optional[int] = None,
    service: str = "inventory-svc",
    starting_heap_mb: int = 320,
    max_heap_mb: int = 2048,
) -> List[LogCreate]:
    """Gradually growing heap, then GC warnings, terminating in OOMError."""
    rng = _rng(seed)
    duration = duration or timedelta(minutes=SCENARIO_META["memory_leak"].default_duration_min)
    t_start, t_end = _ts_range(start, duration)

    logs: List[LogCreate] = []
    total_seconds = duration.total_seconds()
    sample_every = timedelta(seconds=20)

    t = t_start
    while t < t_end:
        progress = (t - t_start).total_seconds() / max(total_seconds, 1.0)
        # Accelerating curve: slow start, steep at the end.
        heap = starting_heap_mb + (max_heap_mb - starting_heap_mb) * (progress ** 1.6)
        heap_int = int(heap + rng.uniform(-15, 15))

        if progress < 0.4:
            logs.append(
                _mk(
                    t,
                    service,
                    "info",
                    f"heap_mb={heap_int} gc_pause_ms={rng.randint(8, 40)} "
                    f"threads={rng.randint(16, 32)} rps={rng.randint(120, 200)}",
                )
            )
        elif progress < 0.75:
            logs.append(
                _mk(
                    t,
                    service,
                    "warning",
                    f"high memory usage heap_mb={heap_int} "
                    f"gc_pause_ms={rng.randint(80, 260)} "
                    f"full_gc_count={rng.randint(1, 8)}",
                )
            )
        else:
            logs.append(
                _mk(
                    t,
                    service,
                    "error",
                    f"GC thrash detected heap_mb={heap_int} "
                    f"gc_pause_ms={rng.randint(400, 1500)} "
                    f"full_gc_count={rng.randint(8, 30)}",
                )
            )

        # Sprinkle in occasional background app logs.
        if rng.random() < 0.3:
            logs.append(
                _background_info(
                    rng, service, t + timedelta(seconds=rng.uniform(1, 8))
                )
            )

        t += sample_every

    # Terminate with an OOM event just before the window ends.
    logs.append(
        _mk(
            t_end - timedelta(seconds=5),
            service,
            "critical",
            f"OutOfMemoryError: Java heap space heap_mb={max_heap_mb} "
            f"thread=pool-3-thread-{rng.randint(1, 32)}",
        )
    )
    logs.append(
        _mk(
            t_end - timedelta(seconds=2),
            service,
            "critical",
            "process terminated exit_code=137 signal=SIGKILL reason=oom_killer",
        )
    )

    logs.sort(key=lambda l: l.timestamp)
    return logs


# ---------------------------------------------------------------------------
# Scenario 3: API latency spike
# ---------------------------------------------------------------------------


def simulate_latency_spike(
    *,
    start: Optional[datetime] = None,
    duration: Optional[timedelta] = None,
    seed: Optional[int] = None,
    service: str = "checkout-svc",
    baseline_ms: int = 80,
    peak_ms: int = 2400,
) -> List[LogCreate]:
    """Latency climbs from baseline to peak_ms, with upstream timeouts at peak."""
    rng = _rng(seed)
    duration = duration or timedelta(minutes=SCENARIO_META["latency_spike"].default_duration_min)
    t_start, t_end = _ts_range(start, duration)

    logs: List[LogCreate] = []
    total_seconds = duration.total_seconds()
    sample_every = timedelta(seconds=5)
    paths = ["/checkout", "/cart/items", "/orders", "/payments/intent"]

    t = t_start
    while t < t_end:
        progress = (t - t_start).total_seconds() / max(total_seconds, 1.0)

        # Baseline until 20%, then ramp up, plateau at peak from 70%.
        if progress < 0.2:
            lat_center = baseline_ms
        elif progress < 0.7:
            factor = (progress - 0.2) / 0.5
            lat_center = baseline_ms + (peak_ms - baseline_ms) * (factor ** 1.4)
        else:
            lat_center = peak_ms

        lat = int(lat_center * rng.uniform(0.75, 1.25))
        path = rng.choice(paths)

        if lat < 300:
            logs.append(
                _mk(
                    t,
                    service,
                    "info",
                    f"request_complete path={path} latency_ms={lat} status=200",
                )
            )
        elif lat < 1000:
            logs.append(
                _mk(
                    t,
                    service,
                    "warning",
                    f"slow_request path={path} latency_ms={lat} "
                    f"p99_window_ms={int(lat * 1.15)} status=200",
                )
            )
        else:
            # At the peak, a fraction of requests time out at the upstream layer.
            if rng.random() < 0.35:
                logs.append(
                    _mk(
                        t,
                        service,
                        "error",
                        f"upstream_timeout path={path} latency_ms={lat} "
                        f"timeout_ms=1000 upstream=payments-svc "
                        f"request_id=r_{rng.randint(100000, 999999)}",
                    )
                )
            else:
                logs.append(
                    _mk(
                        t,
                        service,
                        "error",
                        f"slow_request path={path} latency_ms={lat} status=504",
                    )
                )

        # Occasional background heartbeats.
        if rng.random() < 0.15:
            logs.append(
                _background_info(
                    rng, service, t + timedelta(milliseconds=rng.randint(100, 900))
                )
            )

        t += sample_every

    logs.sort(key=lambda l: l.timestamp)
    return logs


# ---------------------------------------------------------------------------
# Registry + dispatcher
# ---------------------------------------------------------------------------


SCENARIO_REGISTRY: Dict[str, Callable[..., List[LogCreate]]] = {
    "database_failure": simulate_database_failure,
    "memory_leak": simulate_memory_leak,
    "latency_spike": simulate_latency_spike,
}


def list_scenarios() -> List[ScenarioMeta]:
    return list(SCENARIO_META.values())


def generate_scenario(
    name: str,
    *,
    start: Optional[datetime] = None,
    duration_minutes: Optional[int] = None,
    seed: Optional[int] = None,
    service: Optional[str] = None,
) -> List[LogCreate]:
    """Dispatch to a named scenario generator with common options."""
    if name not in SCENARIO_REGISTRY:
        raise ValueError(
            f"Unknown scenario {name!r}. Available: {sorted(SCENARIO_REGISTRY)}"
        )

    kwargs: dict = {"seed": seed}
    if start is not None:
        kwargs["start"] = start
    if duration_minutes is not None:
        kwargs["duration"] = timedelta(minutes=duration_minutes)
    if service is not None:
        kwargs["service"] = service

    return SCENARIO_REGISTRY[name](**kwargs)


__all__ = [
    "ScenarioMeta",
    "SCENARIO_META",
    "SCENARIO_REGISTRY",
    "simulate_database_failure",
    "simulate_memory_leak",
    "simulate_latency_spike",
    "list_scenarios",
    "generate_scenario",
]
