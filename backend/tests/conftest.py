"""Shared pytest fixtures.

By default, ALL tests in this suite run with the vector-memory subsystem
stubbed out via a disabled `MemoryService`. That way:
  - Tests never hit the real Chroma store or download an embedding model.
  - Tests that want to exercise memory behavior can still construct their
    own MemoryService (e.g. with an injected embedder) and install it via
    `memory_service.set_memory_service(my_service)`.
"""

from __future__ import annotations

import pytest

from app.services import memory_service as _memory_service


class _DisabledMemoryService:
    """Drop-in stub that mirrors MemoryService's public surface as a no-op."""

    enabled = False

    def store_incident(self, incident, logs=None) -> bool:  # noqa: ARG002
        return False

    def retrieve_similar_incidents(self, logs, n_results: int = 3):  # noqa: ARG002
        return []

    def reset(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _stub_memory_service():
    """Replace the process-wide memory service with a disabled stub for each test."""
    previous = _memory_service._default_service  # type: ignore[attr-defined]
    _memory_service.set_memory_service(_DisabledMemoryService())  # type: ignore[arg-type]
    try:
        yield
    finally:
        _memory_service.set_memory_service(previous)
