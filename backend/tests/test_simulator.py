"""Tests for the synthetic log generator."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.anomaly_detector import detect_anomalies
from app.services.log_generator import (
    SCENARIO_META,
    generate_scenario,
    simulate_database_failure,
    simulate_latency_spike,
    simulate_memory_leak,
)


FIXED_START = datetime(2026, 4, 23, 14, 0, tzinfo=timezone.utc)


def test_scenarios_are_registered():
    assert set(SCENARIO_META) == {"database_failure", "memory_leak", "latency_spike"}


def test_database_failure_is_deterministic_with_seed():
    a = simulate_database_failure(start=FIXED_START, seed=42)
    b = simulate_database_failure(start=FIXED_START, seed=42)
    assert len(a) == len(b)
    assert [(l.timestamp, l.severity, l.message) for l in a] == [
        (l.timestamp, l.severity, l.message) for l in b
    ]


def test_database_failure_is_sorted_and_produces_errors():
    logs = simulate_database_failure(start=FIXED_START, seed=1)
    assert len(logs) > 20
    timestamps = [l.timestamp for l in logs]
    assert timestamps == sorted(timestamps)

    error_logs = [l for l in logs if l.severity in {"error", "critical"}]
    assert len(error_logs) >= 10
    # Must include the signature phrase.
    assert any("connection timeout to db-primary" in l.message for l in error_logs)
    # Should reference both services.
    services = {l.service_name for l in logs}
    assert "orders-svc" in services
    assert "api-gateway" in services


def test_memory_leak_shows_monotonic_heap_growth():
    logs = simulate_memory_leak(start=FIXED_START, seed=7, duration=timedelta(minutes=20))
    heaps = []
    for l in logs:
        # Pull heap_mb=NNN out of the message when present.
        for token in l.message.split():
            if token.startswith("heap_mb="):
                try:
                    heaps.append(int(token.split("=", 1)[1]))
                except ValueError:
                    pass
    assert len(heaps) >= 10
    # Strong monotonic trend: last value should be much larger than first.
    assert heaps[-1] > heaps[0] * 2
    # And OOM markers appear at the tail.
    tail_messages = " ".join(l.message for l in logs[-5:])
    assert "OutOfMemoryError" in tail_messages
    assert "oom_killer" in tail_messages


def test_latency_spike_ramps_upward():
    logs = simulate_latency_spike(start=FIXED_START, seed=9, duration=timedelta(minutes=15))
    latencies = []
    for l in logs:
        for token in l.message.split():
            if token.startswith("latency_ms="):
                try:
                    latencies.append(int(token.split("=", 1)[1]))
                except ValueError:
                    pass
    assert len(latencies) >= 20

    first_third = latencies[: len(latencies) // 3]
    last_third = latencies[-len(latencies) // 3 :]
    avg_first = sum(first_third) / len(first_third)
    avg_last = sum(last_third) / len(last_third)
    assert avg_last > avg_first * 3, f"expected latency ramp, got {avg_first=} -> {avg_last=}"


def test_generate_scenario_dispatcher_with_override():
    logs = generate_scenario(
        "database_failure",
        start=FIXED_START,
        duration_minutes=5,
        seed=3,
        service="custom-svc",
    )
    assert len(logs) > 0
    assert any(l.service_name == "custom-svc" for l in logs)

    span = max(l.timestamp for l in logs) - min(l.timestamp for l in logs)
    assert span <= timedelta(minutes=5, seconds=10)


def test_generate_scenario_rejects_unknown_name():
    with pytest.raises(ValueError):
        generate_scenario("banana", start=FIXED_START, seed=1)


def test_anomaly_detector_fires_on_database_failure():
    """The whole point of this engine: detector must flag the signal."""
    from types import SimpleNamespace

    logs = simulate_database_failure(start=FIXED_START, seed=11)

    # Attach ids + build ORM-like objects (detector expects Log attributes).
    log_objs = [
        SimpleNamespace(
            id=i,
            timestamp=l.timestamp,
            service_name=l.service_name,
            severity=l.severity,
            message=l.message,
        )
        for i, l in enumerate(logs, start=1)
    ]
    anomalies = detect_anomalies(log_objs)
    kinds = {a.kind for a in anomalies}
    assert "error_spike" in kinds or "repeated_error" in kinds
