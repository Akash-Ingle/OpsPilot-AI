"""Agent tool registry and safe execution layer.

Design:
- Each tool is a plain Python function that returns a `ToolResult`.
- `TOOL_REGISTRY` maps the LLM's `requested_action` string to its function.
- `execute_tool(name, args)` is the single safe entry point used by the
  orchestrator. It handles:
    * unknown tool names (clear error listing available tools)
    * argument validation against the tool's signature
    * exception isolation (tool crashes become errors, not exceptions)
    * structured results that are JSON-serializable and LLM-friendly

Week-1 tool implementations are stubs / mocks. They are swapped for real
implementations (DB queries, metrics API, k8s calls) in later weeks without
changing the public surface.
"""

from __future__ import annotations

import inspect
import json
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from app.core.logging import logger


# ---------------------------------------------------------------------------
# Return types
# ---------------------------------------------------------------------------


@dataclass
class ToolResult:
    """Raw return value from a tool function."""

    ok: bool
    data: Any = None
    error: Optional[str] = None


@dataclass
class ToolExecution:
    """Complete record of an execute_tool() attempt. JSON-serializable."""

    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    ok: bool = False
    data: Any = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "args": dict(self.args),
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
        }

    def to_llm_text(self, max_chars: int = 1200) -> str:
        """Compact rendering for inclusion in a follow-up LLM prompt."""
        header = f"tool_call: {self.name}({_fmt_kwargs(self.args)})"
        if not self.ok:
            return f"{header}\ntool_result: ERROR - {self.error}"
        try:
            payload = json.dumps(self.data, default=str, ensure_ascii=False)
        except Exception:
            payload = str(self.data)
        if len(payload) > max_chars:
            payload = payload[:max_chars] + "... (truncated)"
        return f"{header}\ntool_result: {payload}"


# ---------------------------------------------------------------------------
# Tool implementations (stubs / mocks for Week 1)
# ---------------------------------------------------------------------------


_REL_WINDOW_RE = re.compile(r"(\d+)\s*([smhd])", re.IGNORECASE)
_FETCH_LOGS_LIMIT = 50


def _parse_iso(value: Any) -> Optional[datetime]:
    """Best-effort parse of an ISO-8601 string into a tz-aware datetime."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_time_window(time_range: Any) -> tuple[datetime, datetime]:
    """Resolve a flexible `time_range` into a concrete (start, end) UTC window.

    Accepts:
      - dict: {"start": <ISO>, "end": <ISO>} (either bound optional)
      - relative string: "30m", "1h", "24h", "7d" (optionally prefixed, e.g.
        "last_1h")
      - anything else / unparseable: defaults to the last 24 hours.
    """
    now = datetime.now(timezone.utc)

    if isinstance(time_range, dict):
        end = _parse_iso(time_range.get("end")) or now
        start = _parse_iso(time_range.get("start")) or (end - timedelta(hours=24))
        return start, end

    if isinstance(time_range, str):
        match = _REL_WINDOW_RE.search(time_range)
        if match:
            qty = int(match.group(1))
            unit = match.group(2).lower()
            seconds = qty * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
            return now - timedelta(seconds=seconds), now

    return now - timedelta(hours=24), now


def fetch_logs(
    time_range: str | Dict[str, str],
    service: str | None = None,
    limit: int = _FETCH_LOGS_LIMIT,
) -> ToolResult:
    """Query persisted logs for a service over a time window.

    Reads from the `logs` table via a short-lived session so the agent can pull
    additional context mid-analysis. Returns the most recent matching lines
    (capped at `limit`) in chronological order, newest first.
    """
    # Imported lazily to avoid coupling the tool registry to the DB layer at
    # module import time (keeps tool unit tests lightweight).
    from app.database import SessionLocal
    from app.models.log import Log

    try:
        cap = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        cap = _FETCH_LOGS_LIMIT

    start, end = _parse_time_window(time_range)

    session = SessionLocal()
    try:
        query = session.query(Log).filter(
            Log.timestamp >= start, Log.timestamp <= end
        )
        if service:
            query = query.filter(Log.service_name == service)
        rows = query.order_by(Log.timestamp.desc()).limit(cap).all()
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("fetch_logs: query failed")
        return ToolResult(ok=False, error=f"log query failed: {exc}")
    finally:
        session.close()

    entries = [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "service": r.service_name,
            "severity": r.severity,
            "message": r.message,
        }
        for r in rows
    ]
    return ToolResult(
        ok=True,
        data={
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "service": service,
            "count": len(entries),
            "logs": entries,
        },
    )


def get_metrics(service: str) -> ToolResult:
    """Return mocked CPU/memory/latency metrics for a service."""
    now = datetime.now(timezone.utc)
    points = [
        {
            "ts": (now - timedelta(minutes=i)).isoformat(),
            "cpu": round(random.uniform(10, 95), 2),
            "memory_mb": round(random.uniform(200, 1800), 2),
            "latency_ms": round(random.uniform(20, 1500), 2),
        }
        for i in range(10, 0, -1)
    ]
    return ToolResult(ok=True, data={"service": service, "metrics": points})


def restart_service(service_name: str) -> ToolResult:
    """Simulate a service restart."""
    return ToolResult(
        ok=True, data={"action": "restart", "service": service_name, "status": "ok"}
    )


def scale_service(service_name: str, replicas: int) -> ToolResult:
    """Simulate scaling a service."""
    if replicas < 1 or replicas > 100:
        return ToolResult(
            ok=False, data=None, error="replicas must be between 1 and 100"
        )
    return ToolResult(
        ok=True,
        data={
            "action": "scale",
            "service": service_name,
            "replicas": replicas,
            "status": "ok",
        },
    )


TOOL_REGISTRY: Dict[str, Callable[..., ToolResult]] = {
    "fetch_logs": fetch_logs,
    "get_metrics": get_metrics,
    "restart_service": restart_service,
    "scale_service": scale_service,
}


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------


def list_tool_specs() -> List[Dict[str, Any]]:
    """Descriptions derived from each tool's signature - safe for prompts."""
    specs: List[Dict[str, Any]] = []
    for name, fn in TOOL_REGISTRY.items():
        sig = inspect.signature(fn)
        params = []
        for pname, p in sig.parameters.items():
            required = p.default is inspect.Parameter.empty
            params.append({"name": pname, "required": required})
        specs.append({"name": name, "params": params})
    return specs


# ---------------------------------------------------------------------------
# Safe execution
# ---------------------------------------------------------------------------


def _fmt_kwargs(args: Dict[str, Any]) -> str:
    if not args:
        return ""
    return ", ".join(f"{k}={json.dumps(v, default=str)}" for k, v in args.items())


def _validate_args(fn: Callable, args: Dict[str, Any]) -> Optional[str]:
    """Return an error message if args don't match fn's signature, else None."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None  # cannot introspect; let the call itself fail

    params = sig.parameters

    has_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
    )
    allowed_kw = [
        name
        for name, p in params.items()
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    ]

    if not has_var_keyword:
        unknown = sorted(k for k in args if k not in params)
        if unknown:
            return (
                f"unknown argument(s) {unknown}; expected one of {allowed_kw}"
            )

    missing = [
        name
        for name, p in params.items()
        if p.default is inspect.Parameter.empty
        and p.kind
        in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
        and name not in args
    ]
    if missing:
        return f"missing required argument(s): {missing}; expected {allowed_kw}"

    return None


def execute_tool(
    name: str,
    args: Optional[Dict[str, Any]] = None,
) -> ToolExecution:
    """Safely dispatch a tool by name.

    Args:
        name: Tool identifier as declared in `TOOL_REGISTRY`. This is also
            the value of `LLMStructuredOutput.requested_action`.
        args: Keyword arguments for the tool.

    Returns:
        `ToolExecution` with ok/data/error fields populated. This function
        never raises - all failure modes are captured in the result.
    """
    args = dict(args) if args else {}
    logger.debug("execute_tool: name={} args={}", name, args)

    tool_fn = TOOL_REGISTRY.get(name)
    if tool_fn is None:
        available = sorted(TOOL_REGISTRY)
        err = f"unknown tool {name!r}. Available tools: {available}"
        logger.warning("execute_tool: {}", err)
        return ToolExecution(name=name, args=args, ok=False, error=err)

    validation_error = _validate_args(tool_fn, args)
    if validation_error:
        err = f"argument validation failed for {name!r}: {validation_error}"
        logger.warning("execute_tool: {}", err)
        return ToolExecution(name=name, args=args, ok=False, error=err)

    try:
        raw = tool_fn(**args)
    except Exception as exc:
        logger.exception("execute_tool: tool {!r} raised", name)
        return ToolExecution(
            name=name,
            args=args,
            ok=False,
            error=f"{name} raised {type(exc).__name__}: {exc}",
        )

    # Tolerate tools that don't use ToolResult (return raw data).
    if not isinstance(raw, ToolResult):
        return ToolExecution(name=name, args=args, ok=True, data=raw)

    execution = ToolExecution(
        name=name,
        args=args,
        ok=raw.ok,
        data=raw.data,
        error=raw.error,
    )
    logger.info(
        "execute_tool: name={} ok={} error={}",
        execution.name,
        execution.ok,
        execution.error,
    )
    return execution


__all__ = [
    "ToolResult",
    "ToolExecution",
    "TOOL_REGISTRY",
    "execute_tool",
    "fetch_logs",
    "get_metrics",
    "restart_service",
    "scale_service",
    "list_tool_specs",
]
