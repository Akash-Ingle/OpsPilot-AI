"""Incident memory service backed by a Chroma vector database (Plan §10.1).

Stores resolved incidents (title, root cause, fix, representative log excerpt)
as embeddings, and retrieves the top-K semantically similar past incidents for
a new set of logs. This lets the agent surface "we've seen this before" context
in its prompt, improving diagnosis quality.

Public API
----------
- `MemoryService` : class wrapping a persistent Chroma collection.
- `store_incident(incident, logs=None)`          : module-level convenience.
- `retrieve_similar_incidents(logs, n_results=3)`: module-level convenience.
- `get_memory_service()` / `set_memory_service(svc)` : singleton accessors.

Design notes
------------
- Embeddings default to Chroma's built-in all-MiniLM-L6-v2 (runs locally, no
  API key required). You can inject any `Callable[[list[str]], list[list[float]]]`
  via the `embedder` kwarg - useful for tests or for switching to OpenAI/Voyage
  embeddings later without touching callers.
- The service NEVER raises into its callers. If Chroma cannot be initialized
  (missing native deps, read-only FS, etc.) the service degrades to a no-op:
  `store_incident` returns False and `retrieve_similar_incidents` returns [].
  This keeps the agent loop robust when memory is unavailable.
- Incidents are upserted by string(incident.id), so re-analyzing the same
  incident refreshes its stored vector instead of duplicating.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from app.config import settings
from app.core.logging import logger

EmbedderFn = Callable[[List[str]], List[List[float]]]

_DEFAULT_COLLECTION = "opspilot_incidents"
_MAX_LOG_EXCERPT_CHARS = 2000
_QUERY_TEXT_MAX_CHARS = 1500
_ERROR_LEVELS = {"error", "critical", "fatal"}


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass
class SimilarIncident:
    """A retrieved historical incident, with similarity metadata."""

    incident_id: Optional[int]
    title: str
    severity: Optional[str]
    root_cause: Optional[str]
    fix: Optional[str]
    distance: float  # lower = more similar (cosine distance)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "title": self.title,
            "severity": self.severity,
            "root_cause": self.root_cause,
            "fix": self.fix,
            "distance": self.distance,
        }


# ---------------------------------------------------------------------------
# Text builders (shared by store + retrieve so embeddings align semantically)
# ---------------------------------------------------------------------------


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        for name in names:
            if name in obj and obj[name] is not None:
                return obj[name]
        return default
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return default


def _sev_str(value: Any) -> str:
    if value is None:
        return ""
    return str(getattr(value, "value", value)).lower()


def _build_incident_document(incident: Any, logs: Optional[Sequence[Any]]) -> str:
    """Create the single text document that represents an incident in the store.

    The format below is ALSO what we aim for at query time (via _build_query_text),
    so the embeddings live in a compatible semantic space.
    """
    title = str(_get(incident, "title", default="") or "").strip()
    severity = _sev_str(_get(incident, "severity"))
    root_cause = str(_get(incident, "root_cause", default="") or "").strip()
    fix = str(_get(incident, "suggested_fix", "fix", default="") or "").strip()

    parts: List[str] = []
    if title:
        parts.append(f"Incident: {title}")
    if severity:
        parts.append(f"Severity: {severity}")
    if root_cause:
        parts.append(f"Root cause: {root_cause}")
    if fix:
        parts.append(f"Fix: {fix}")
    if logs:
        excerpt = _summarize_logs_for_embedding(logs)
        if excerpt:
            parts.append(f"Representative logs:\n{excerpt}")

    return "\n".join(parts).strip() or (title or "incident")


def _build_query_text(logs: Sequence[Any]) -> str:
    """Turn a stream of logs into a query string that mirrors the stored docs."""
    excerpt = _summarize_logs_for_embedding(logs)
    if not excerpt:
        return ""
    return f"Representative logs:\n{excerpt}"


def _summarize_logs_for_embedding(logs: Sequence[Any]) -> str:
    """Extract a deduplicated, error-biased digest of the most informative logs.

    The goal is stable, semantically-loaded text for embedding - not pretty
    formatting. We prioritize error/critical messages and dedupe near-identical
    ones to avoid biasing the embedding toward repetitive noise.
    """
    if not logs:
        return ""

    # Partition by error-ness; keep chronological order within each group.
    errors: List[Any] = []
    others: List[Any] = []
    for log in logs:
        sev = _sev_str(_get(log, "severity", default="info"))
        (errors if sev in _ERROR_LEVELS else others).append(log)

    ordered = errors + others

    seen: set[str] = set()
    lines: List[str] = []
    total_chars = 0
    for log in ordered:
        msg = str(_get(log, "message", default="") or "").strip()
        if not msg:
            continue
        key = msg[:120]  # dedup key - tolerates minor trailing differences
        if key in seen:
            continue
        seen.add(key)

        service = str(_get(log, "service_name", "service", default="") or "")
        sev = _sev_str(_get(log, "severity", default="")).upper()
        prefix_bits = [b for b in (sev, service) if b]
        line = f"[{' '.join(prefix_bits)}] {msg}" if prefix_bits else msg

        if total_chars + len(line) > _MAX_LOG_EXCERPT_CHARS:
            break
        lines.append(line)
        total_chars += len(line)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MemoryService:
    """Vector-memory wrapper around a single Chroma collection.

    Init is lazy and defensive: if Chroma is not importable or fails to open
    the persistent store, the service silently enters `disabled` mode. All
    public methods remain callable and return safe defaults in that state.
    """

    def __init__(
        self,
        path: Optional[str] = None,
        collection_name: str = _DEFAULT_COLLECTION,
        embedder: Optional[EmbedderFn] = None,
    ) -> None:
        self._path = path if path is not None else settings.vector_db_path
        self._collection_name = collection_name
        self._embedder = embedder
        self._client = None
        self._collection = None
        self._disabled_reason: Optional[str] = None
        self._init_store()

    # -- init ---------------------------------------------------------------

    def _init_store(self) -> None:
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
        except Exception as exc:  # pragma: no cover - import guarded
            self._disabled_reason = f"chromadb import failed: {exc}"
            logger.warning("MemoryService disabled: {}", self._disabled_reason)
            return

        try:
            self._client = chromadb.PersistentClient(
                path=self._path,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "MemoryService ready (path={} collection='{}' count={})",
                self._path,
                self._collection_name,
                self._safe_count(),
            )
        except Exception as exc:  # pragma: no cover - environment-dependent
            self._client = None
            self._collection = None
            self._disabled_reason = f"chroma init failed: {exc}"
            logger.warning("MemoryService disabled: {}", self._disabled_reason)

    @property
    def enabled(self) -> bool:
        return self._collection is not None

    def _safe_count(self) -> int:
        try:
            return int(self._collection.count()) if self._collection else 0
        except Exception:  # pragma: no cover
            return 0

    # -- embedding ----------------------------------------------------------

    def _embed(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of strings; caches Chroma's default embedder if unset."""
        if self._embedder is None:
            self._embedder = _load_default_embedder()
        return self._embedder(texts)

    # -- public API ---------------------------------------------------------

    def store_incident(
        self,
        incident: Any,
        logs: Optional[Sequence[Any]] = None,
    ) -> bool:
        """Upsert one incident into the vector store. Returns True on success.

        `incident` must expose `id`, `title`, `severity`, `root_cause`, and
        `suggested_fix` (the shape of our `Incident` ORM model). Attrs OR dict
        keys both work. `logs` is optional: if provided, a deduped error-biased
        excerpt is embedded alongside the incident metadata.
        """
        if not self.enabled:
            return False

        document = _build_incident_document(incident, logs)
        if not document:
            logger.debug("store_incident: skipping empty document")
            return False

        incident_id = _get(incident, "id")
        doc_id = str(incident_id) if incident_id is not None else f"auto-{id(incident)}"

        metadata: Dict[str, Any] = {
            "incident_id": int(incident_id) if isinstance(incident_id, int) else -1,
            "title": str(_get(incident, "title", default="") or "")[:500],
            "severity": _sev_str(_get(incident, "severity")) or "unknown",
            "root_cause": str(_get(incident, "root_cause", default="") or "")[:2000],
            "fix": str(
                _get(incident, "suggested_fix", "fix", default="") or ""
            )[:2000],
        }

        try:
            embedding = self._embed([document])[0]
        except Exception as exc:
            logger.warning("store_incident: embedding failed ({}); skipping", exc)
            return False

        try:
            self._collection.upsert(  # type: ignore[union-attr]
                ids=[doc_id],
                documents=[document],
                embeddings=[embedding],
                metadatas=[metadata],
            )
        except Exception as exc:
            logger.warning("store_incident: upsert failed ({}); skipping", exc)
            return False

        logger.info(
            "memory: stored incident id={} title='{}' (doc_id={})",
            incident_id,
            metadata["title"][:80],
            doc_id,
        )
        return True

    def retrieve_similar_incidents(
        self,
        logs: Sequence[Any],
        n_results: int = 3,
    ) -> List[SimilarIncident]:
        """Return up to `n_results` past incidents most similar to these logs.

        Returns an empty list if:
          - the service is disabled,
          - the collection is empty,
          - `logs` yields no meaningful query text,
          - embedding or query fails.
        """
        if not self.enabled:
            return []

        n_results = max(1, min(int(n_results), 20))

        if self._safe_count() == 0:
            return []

        query_text = _build_query_text(logs)
        if not query_text.strip():
            return []
        query_text = query_text[:_QUERY_TEXT_MAX_CHARS]

        try:
            embedding = self._embed([query_text])[0]
        except Exception as exc:
            logger.warning("retrieve_similar_incidents: embedding failed ({})", exc)
            return []

        try:
            raw = self._collection.query(  # type: ignore[union-attr]
                query_embeddings=[embedding],
                n_results=n_results,
                include=["metadatas", "distances"],
            )
        except Exception as exc:
            logger.warning("retrieve_similar_incidents: query failed ({})", exc)
            return []

        metadatas = (raw.get("metadatas") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]

        results: List[SimilarIncident] = []
        for meta, dist in zip(metadatas, distances):
            meta = meta or {}
            raw_id = meta.get("incident_id")
            incident_id: Optional[int]
            incident_id = int(raw_id) if isinstance(raw_id, int) and raw_id >= 0 else None
            results.append(
                SimilarIncident(
                    incident_id=incident_id,
                    title=str(meta.get("title") or "").strip() or "(untitled)",
                    severity=(meta.get("severity") or None),
                    root_cause=(meta.get("root_cause") or None),
                    fix=(meta.get("fix") or None),
                    distance=float(dist) if dist is not None else float("nan"),
                )
            )

        logger.info(
            "memory: retrieved {} similar incident(s) for {} log(s)",
            len(results),
            len(logs),
        )
        return results

    def reset(self) -> None:
        """Drop and recreate the collection. Mostly for tests / admin use."""
        if not self._client:
            return
        try:
            self._client.delete_collection(self._collection_name)
        except Exception:
            pass
        try:
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("memory reset failed: {}", exc)
            self._collection = None


# ---------------------------------------------------------------------------
# Default embedder loader (lazy - avoids loading ONNX model at import time)
# ---------------------------------------------------------------------------


def _load_default_embedder() -> EmbedderFn:
    """Return a callable that embeds strings using Chroma's default model.

    Chroma's `DefaultEmbeddingFunction` downloads all-MiniLM-L6-v2 on first use
    (runs locally via onnxruntime). We wrap it so callers see a plain function
    signature and we keep all vendor-lock-in contained here.
    """
    from chromadb.utils import embedding_functions  # local import keeps cold start cheap

    fn = embedding_functions.DefaultEmbeddingFunction()

    def _embed(texts: List[str]) -> List[List[float]]:
        return [list(vec) for vec in fn(texts)]  # normalize to plain lists

    return _embed


# ---------------------------------------------------------------------------
# Module-level singleton + convenience functions
# ---------------------------------------------------------------------------


_default_service: Optional[MemoryService] = None


def get_memory_service() -> MemoryService:
    """Return the process-wide MemoryService, constructing it on first access."""
    global _default_service
    if _default_service is None:
        _default_service = MemoryService()
    return _default_service


def set_memory_service(service: Optional[MemoryService]) -> None:
    """Override the process-wide MemoryService (mainly for tests)."""
    global _default_service
    _default_service = service


def store_incident(
    incident: Any, logs: Optional[Sequence[Any]] = None
) -> bool:
    """Module-level convenience wrapper around the singleton service."""
    return get_memory_service().store_incident(incident, logs)


def retrieve_similar_incidents(
    logs: Sequence[Any], n_results: int = 3
) -> List[SimilarIncident]:
    """Module-level convenience wrapper around the singleton service."""
    return get_memory_service().retrieve_similar_incidents(logs, n_results)


__all__ = [
    "MemoryService",
    "SimilarIncident",
    "get_memory_service",
    "set_memory_service",
    "store_incident",
    "retrieve_similar_incidents",
]
