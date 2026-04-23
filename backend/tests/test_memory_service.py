"""Tests for the incident-memory service.

These tests exercise MemoryService against a real Chroma PersistentClient (in a
tmp dir) but with an injected deterministic embedder - so they don't require
downloading the default ONNX model and remain fully hermetic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List

import pytest

from app.services.memory_service import (
    MemoryService,
    SimilarIncident,
    _build_incident_document,
    _build_query_text,
    _summarize_logs_for_embedding,
)

pytest.importorskip("chromadb")


# ---------------------------------------------------------------------------
# Test fixtures - simple types + a deterministic embedder
# ---------------------------------------------------------------------------


@dataclass
class FakeIncident:
    id: int
    title: str
    severity: str
    root_cause: str
    suggested_fix: str


@dataclass
class FakeLog:
    service_name: str
    severity: str
    message: str


_VOCAB = [
    "database", "connection", "timeout", "pool", "exhausted",
    "memory", "leak", "oom", "heap", "gc",
    "latency", "spike", "slow", "timeout", "5xx",
    "circuit", "breaker", "scale", "replicas", "retry",
]


def _tiny_embedder(texts: List[str]) -> List[List[float]]:
    """Bag-of-words embedder over a fixed vocab. Deterministic + fast.

    Same content -> identical vectors. Semantically similar content (shared
    vocabulary) -> small cosine distance. Great for asserting real retrieval
    ordering without pulling in a heavy model.
    """
    vectors: List[List[float]] = []
    for text in texts:
        tokens = text.lower().split()
        vec = [float(tokens.count(word)) for word in _VOCAB]
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        vectors.append([v / norm for v in vec])
    return vectors


@pytest.fixture
def svc(tmp_path):
    """A fresh MemoryService backed by a tmp Chroma store and the tiny embedder."""
    service = MemoryService(
        path=str(tmp_path / "chroma"),
        collection_name="test_incidents",
        embedder=_tiny_embedder,
    )
    assert service.enabled, "MemoryService should initialize under pytest tmp_path"
    return service


# ---------------------------------------------------------------------------
# Document / query text builders
# ---------------------------------------------------------------------------


def test_build_incident_document_includes_all_fields():
    inc = FakeIncident(
        id=1,
        title="DB pool exhausted",
        severity="high",
        root_cause="circuit breaker missing",
        suggested_fix="increase pool to 50",
    )
    doc = _build_incident_document(inc, logs=None)
    assert "Incident: DB pool exhausted" in doc
    assert "Severity: high" in doc
    assert "Root cause: circuit breaker missing" in doc
    assert "Fix: increase pool to 50" in doc


def test_build_incident_document_handles_missing_fields():
    class Bare:
        id = 99
        title = "minimal"
        severity = None
        root_cause = None
        suggested_fix = None
    doc = _build_incident_document(Bare(), logs=None)
    assert doc.startswith("Incident: minimal")
    assert "Root cause" not in doc
    assert "Fix" not in doc


def test_summarize_logs_for_embedding_prioritizes_errors_and_dedups():
    logs = [
        FakeLog("svc", "info", "starting"),
        FakeLog("svc", "error", "connection timeout to db"),
        FakeLog("svc", "error", "connection timeout to db"),  # duplicate
        FakeLog("svc", "error", "connection timeout to db"),  # duplicate
        FakeLog("svc", "warning", "slow query"),
    ]
    excerpt = _summarize_logs_for_embedding(logs)
    # Errors appear before infos.
    assert excerpt.index("connection timeout") < excerpt.index("starting")
    # The duplicate error message is deduped.
    assert excerpt.count("connection timeout to db") == 1


def test_build_query_text_empty_when_no_logs():
    assert _build_query_text([]) == ""


# ---------------------------------------------------------------------------
# Store + retrieve round-trip
# ---------------------------------------------------------------------------


def test_store_and_retrieve_exact_match(svc):
    inc = FakeIncident(
        id=42,
        title="db timeout",
        severity="high",
        root_cause="database connection pool exhausted",
        suggested_fix="increase pool",
    )
    logs = [FakeLog("api", "error", "database connection timeout")]

    assert svc.store_incident(inc, logs=logs) is True

    query_logs = [FakeLog("api", "error", "database connection timeout")]
    results = svc.retrieve_similar_incidents(query_logs, n_results=3)

    assert len(results) == 1
    assert isinstance(results[0], SimilarIncident)
    assert results[0].incident_id == 42
    assert results[0].title == "db timeout"
    assert results[0].severity == "high"
    assert results[0].root_cause.startswith("database connection pool")
    # Same text -> cosine distance near zero.
    assert results[0].distance < 0.01


def test_retrieve_ranks_semantically_similar_first(svc):
    db_inc = FakeIncident(
        id=1,
        title="db outage",
        severity="high",
        root_cause="database connection pool exhausted",
        suggested_fix="scale replicas",
    )
    db_logs = [FakeLog("api", "error", "database connection timeout pool exhausted")]

    mem_inc = FakeIncident(
        id=2,
        title="oom",
        severity="critical",
        root_cause="memory leak caused heap growth",
        suggested_fix="bump heap",
    )
    mem_logs = [FakeLog("worker", "error", "memory leak heap oom")]

    lat_inc = FakeIncident(
        id=3,
        title="latency",
        severity="medium",
        root_cause="latency spike on slow backend",
        suggested_fix="add circuit breaker",
    )
    lat_logs = [FakeLog("gateway", "warning", "latency spike slow 5xx")]

    assert svc.store_incident(db_inc, logs=db_logs)
    assert svc.store_incident(mem_inc, logs=mem_logs)
    assert svc.store_incident(lat_inc, logs=lat_logs)

    # Query strongly about DB -> the DB incident must come first.
    query_logs = [FakeLog("api", "error", "database connection timeout pool")]
    results = svc.retrieve_similar_incidents(query_logs, n_results=3)
    assert len(results) == 3
    assert results[0].incident_id == 1
    # Distance is non-decreasing.
    distances = [r.distance for r in results]
    assert distances == sorted(distances)


def test_upsert_refreshes_existing_incident(svc):
    inc = FakeIncident(1, "db outage", "high", "pool exhausted", "scale")
    svc.store_incident(inc, logs=[FakeLog("api", "error", "database timeout")])
    svc.store_incident(
        FakeIncident(1, "db outage v2", "critical", "new cause", "new fix"),
        logs=[FakeLog("api", "error", "database timeout")],
    )
    results = svc.retrieve_similar_incidents(
        [FakeLog("api", "error", "database timeout")], n_results=5
    )
    # Still exactly one entry for incident id=1.
    assert len([r for r in results if r.incident_id == 1]) == 1
    # Metadata reflects the latest write.
    top = next(r for r in results if r.incident_id == 1)
    assert top.title == "db outage v2"
    assert top.severity == "critical"


def test_retrieve_respects_n_results(svc):
    for i in range(5):
        svc.store_incident(
            FakeIncident(i, f"incident {i}", "medium", f"cause {i}", f"fix {i}"),
            logs=[FakeLog("svc", "error", f"database error number {i}")],
        )
    results = svc.retrieve_similar_incidents(
        [FakeLog("svc", "error", "database error")], n_results=2
    )
    assert len(results) == 2


def test_retrieve_empty_collection_returns_empty(svc):
    assert svc.retrieve_similar_incidents(
        [FakeLog("svc", "error", "database timeout")], n_results=3
    ) == []


def test_retrieve_with_empty_logs_returns_empty(svc):
    svc.store_incident(
        FakeIncident(1, "x", "low", "y", "z"),
        logs=[FakeLog("a", "error", "database timeout")],
    )
    assert svc.retrieve_similar_incidents([], n_results=3) == []


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


def test_disabled_service_is_safe_noop():
    """If init fails, service is disabled; store returns False, retrieve returns []."""
    svc = MemoryService.__new__(MemoryService)  # bypass __init__
    svc._client = None
    svc._collection = None
    svc._embedder = None
    svc._disabled_reason = "forced disabled for test"

    assert svc.enabled is False
    assert svc.store_incident(
        FakeIncident(1, "x", "low", "y", "z"),
        logs=[FakeLog("a", "error", "m")],
    ) is False
    assert svc.retrieve_similar_incidents(
        [FakeLog("a", "error", "m")], n_results=3
    ) == []


def test_store_with_embedding_failure_returns_false(svc):
    def boom(_texts):
        raise RuntimeError("embedding backend down")

    svc._embedder = boom
    ok = svc.store_incident(
        FakeIncident(1, "x", "low", "y", "z"),
        logs=[FakeLog("a", "error", "m")],
    )
    assert ok is False


def test_retrieve_with_embedding_failure_returns_empty(svc):
    svc.store_incident(
        FakeIncident(1, "x", "low", "y", "z"),
        logs=[FakeLog("a", "error", "database timeout")],
    )

    def boom(_texts):
        raise RuntimeError("embedding backend down")

    svc._embedder = boom
    assert svc.retrieve_similar_incidents(
        [FakeLog("a", "error", "database timeout")], n_results=3
    ) == []
