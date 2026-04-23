"""Parse raw log payloads (JSON or plain text) into LogCreate schemas."""

import json
import re
from datetime import datetime, timezone
from typing import Iterable, List

from dateutil import parser as dateparser

from app.schemas.log import LogCreate

# Matches patterns like:
#   2026-04-23T12:34:56Z [ERROR] api-gateway: connection timeout
#   2026-04-23 12:34:56 ERROR api-gateway connection timeout
_TEXT_LINE = re.compile(
    r"""^
    (?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)
    \s*[\[\s]?
    (?P<severity>TRACE|DEBUG|INFO|NOTICE|WARN(?:ING)?|ERROR|CRITICAL|FATAL)
    [\]\s]+
    (?:(?P<service>[\w.\-]+)\s*[:\-]\s*)?
    (?P<message>.+)
    $""",
    re.IGNORECASE | re.VERBOSE,
)

_VALID_SEVERITIES = {"trace", "debug", "info", "notice", "warn", "warning", "error", "critical", "fatal"}


def _normalize_severity(raw: str) -> str:
    sev = raw.strip().lower()
    if sev == "warn":
        return "warning"
    return sev if sev in _VALID_SEVERITIES else "info"


def _to_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        dt = dateparser.parse(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    raise ValueError(f"Unsupported timestamp: {value!r}")


def _from_json_obj(obj: dict) -> LogCreate | None:
    ts_raw = obj.get("timestamp") or obj.get("ts") or obj.get("time") or obj.get("@timestamp")
    if not ts_raw:
        return None
    service = obj.get("service") or obj.get("service_name") or obj.get("app") or "unknown"
    severity = obj.get("severity") or obj.get("level") or "info"
    message = obj.get("message") or obj.get("msg") or ""
    try:
        return LogCreate(
            timestamp=_to_dt(ts_raw),
            service_name=str(service)[:128],
            severity=_normalize_severity(str(severity)),
            message=str(message),
        )
    except Exception:
        return None


def _from_text_line(line: str) -> LogCreate | None:
    match = _TEXT_LINE.match(line.strip())
    if not match:
        return None
    try:
        return LogCreate(
            timestamp=_to_dt(match.group("ts")),
            service_name=(match.group("service") or "unknown")[:128],
            severity=_normalize_severity(match.group("severity")),
            message=match.group("message").strip(),
        )
    except Exception:
        return None


def parse_log_payload(raw: str, filename: str = "") -> List[LogCreate]:
    """Parse a raw log payload into a list of LogCreate entries.

    Supports:
    - JSON array of objects
    - Newline-delimited JSON (jsonl)
    - Plain text lines matching a common timestamp/level/service/message format
    """
    raw = raw.strip()
    if not raw:
        return []

    # Try JSON array first.
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [entry for obj in data if isinstance(obj, dict) and (entry := _from_json_obj(obj))]
        except json.JSONDecodeError:
            pass

    entries: List[LogCreate] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # JSONL
        if line.startswith("{"):
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    parsed = _from_json_obj(obj)
                    if parsed:
                        entries.append(parsed)
                        continue
            except json.JSONDecodeError:
                pass
        # Plain text line
        parsed = _from_text_line(line)
        if parsed:
            entries.append(parsed)

    return entries


__all__ = ["parse_log_payload"]
