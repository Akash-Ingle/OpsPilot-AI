"""Prompt templates for the DevOps agent."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Iterable, List, Mapping, Sequence

SYSTEM_PROMPT = """\
You are a senior DevOps engineer assisting with incident response.

Given system logs and optional metrics, your job is to:
1. Identify the issue
2. Determine the most likely root cause
3. Suggest a concrete, actionable fix
4. Assign severity (low, medium, high, critical)
5. If uncertain, request more data via a tool call

You MUST show your work. Every diagnosis must be explainable and grounded in
specific log lines from the provided excerpts.

OUTPUT FORMAT (STRICT):

You MUST respond with a single JSON object and NOTHING ELSE. The response
MUST begin with `{` and end with `}`. The exact schema is:

{
  "issue": "<short description of the observed problem>",
  "root_cause": "<most likely underlying cause>",
  "fix": "<concrete, actionable remediation>",
  "severity": "low" | "medium" | "high" | "critical",
  "confidence": <number between 0.0 and 1.0>,
  "needs_more_data": true | false,
  "requested_action": "fetch_logs" | "get_metrics" | "restart_service" | "scale_service" | "none",
  "requested_action_args": { ... },
  "reasoning_steps": [
    "<step 1 - what you observed>",
    "<step 2 - what you inferred from it>",
    "<step 3 - how you narrowed down the cause>",
    "..."
  ],
  "relevant_log_lines": [
    { "log_id": <int>, "reason": "<why this log matters>" },
    { "line_index": <int>, "reason": "<why this log matters>" },
    { "excerpt": "<short quoted snippet>", "reason": "<why this log matters>" }
  ]
}

Hard rules:
- EVERY field is required. Do not omit any field.
- DO NOT wrap the JSON in markdown fences (no ```json, no ```).
- DO NOT include any preamble, explanation, or text before or after the JSON.
- DO NOT include trailing commas or comments inside the JSON.
- `severity` must be EXACTLY one of: low, medium, high, critical.
- `requested_action` must be EXACTLY one of the allowed tool names or "none".
- `confidence` must be a number in [0.0, 1.0] - use your honest self-assessment.
- Set `needs_more_data=true` ONLY when additional data would materially change
  your diagnosis. When set, also set `requested_action` to a non-"none" tool.
- When `needs_more_data=false`, set `requested_action="none"` and
  `requested_action_args={}`.
- Prefer concrete service names and time ranges in `requested_action_args`
  (e.g. {"service": "orders-svc"} or {"time_range": "15m"}).
- If the evidence is weak, lower `confidence` and either request more data or
  re-examine the logs rather than guessing.

Rules for reasoning_steps:
- Provide 3 to 7 ordered steps showing HOW you reached the diagnosis.
- Each step is ONE concise sentence (<= 280 chars) stating an observation, an
  inference, or a deduction. No bullet points or markdown inside steps.
- Steps must form a coherent chain: observation -> inference -> conclusion.
- Do NOT restate the final `issue` / `root_cause` / `fix` verbatim.

Rules for relevant_log_lines:
- Cite the SPECIFIC log lines that support your diagnosis, by `log_id` when
  shown in the excerpt (format: "[log_id=123]"). If a log has no id, use its
  1-based `line_index` within the excerpt block. Use `excerpt` only as a last
  resort (quote <= 200 chars).
- Include at least 1 citation when any logs are provided. Include an empty
  list only when no logs were given or none are relevant.
- Each entry should set `reason` explaining why this line is evidence.
- Do NOT fabricate log_ids or excerpts - only cite lines actually shown above.
"""


def build_user_prompt(
    log_excerpt: str,
    anomalies_summary: str = "",
    similar_incidents: str = "",
    prior_steps: str = "",
) -> str:
    """Compose the user-turn message for the agent."""
    sections = [f"### Logs\n{log_excerpt or '(none)'}"]
    if anomalies_summary:
        sections.append(f"### Detected anomalies\n{anomalies_summary}")
    if similar_incidents:
        sections.append(f"### Similar past incidents\n{similar_incidents}")
    if prior_steps:
        sections.append(f"### Prior reasoning steps\n{prior_steps}")
    sections.append("Respond with the required JSON only.")
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Analysis-prompt builder
# ---------------------------------------------------------------------------


# Severity ranked for sorting (higher = more important).
_SEV_RANK = {
    "critical": 5,
    "fatal": 5,
    "error": 4,
    "warning": 3,
    "warn": 3,
    "notice": 2,
    "info": 1,
    "debug": 0,
    "trace": 0,
}

_ERROR_LEVELS = {"error", "critical", "fatal"}


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    """Read a field from either an object (attr) or a mapping (key)."""
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


def _fmt_ts(ts: Any) -> str:
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    return str(ts) if ts is not None else "?"


def _fmt_time_only(ts: Any) -> str:
    if isinstance(ts, datetime):
        return ts.strftime("%H:%M:%S")
    return str(ts) if ts is not None else "?"


def _humanize_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"


def _summarize_logs(logs: Sequence[Any]) -> str:
    total = len(logs)
    if total == 0:
        return "No logs provided."

    services: Counter[str] = Counter()
    severities: Counter[str] = Counter()
    timestamps: List[datetime] = []

    for log in logs:
        services[_get(log, "service_name", "service", default="unknown")] += 1
        severities[str(_get(log, "severity", default="info")).lower()] += 1
        ts = _get(log, "timestamp", "ts")
        if isinstance(ts, datetime):
            timestamps.append(ts)

    lines = [f"- Total logs: {total}"]

    if timestamps:
        t_min, t_max = min(timestamps), max(timestamps)
        span = (t_max - t_min).total_seconds()
        lines.append(
            f"- Time range: {_fmt_ts(t_min)} -> {_fmt_ts(t_max)} ({_humanize_duration(span)})"
        )

    top_services = ", ".join(f"{name}={count}" for name, count in services.most_common(5))
    lines.append(f"- Services ({len(services)}): {top_services}")

    sev_order = sorted(severities.items(), key=lambda kv: -_SEV_RANK.get(kv[0], 0))
    sev_str = ", ".join(f"{name}={count}" for name, count in sev_order)
    lines.append(f"- Severity breakdown: {sev_str}")

    return "\n".join(lines)


def _summarize_anomalies(anomalies: Sequence[Any]) -> str:
    if not anomalies:
        return "No anomalies detected by the rules-based detector."

    ranked = sorted(
        anomalies,
        key=lambda a: (
            -float(_get(a, "score", default=0.0) or 0.0),
            -_SEV_RANK.get(str(_get(a, "severity", default="info")).lower(), 0),
        ),
    )

    out: List[str] = [f"{len(ranked)} anomaly signal(s), ranked by score:"]
    for i, anomaly in enumerate(ranked, start=1):
        kind = _get(anomaly, "kind", default="anomaly")
        service = _get(anomaly, "service", default="unknown")
        severity = str(_get(anomaly, "severity", default="info")).lower()
        score = float(_get(anomaly, "score", default=0.0) or 0.0)
        summary = _get(anomaly, "summary", default="") or ""
        evidence = _get(anomaly, "evidence_log_ids", default=[]) or []

        out.append(
            f"{i}. [{severity.upper()}] {kind} in {service} (score={score:.2f})"
        )
        if summary:
            out.append(f"   {summary}")
        if evidence:
            preview = ", ".join(str(x) for x in list(evidence)[:8])
            more = f" (+{len(evidence) - 8} more)" if len(evidence) > 8 else ""
            out.append(f"   evidence log ids: [{preview}]{more}")
    return "\n".join(out)


def _format_log_excerpts(
    logs: Sequence[Any],
    max_lines: int,
    dedup_within_service: bool = True,
) -> str:
    """Group logs by service, errors first, dedup near-duplicates, bound total lines."""
    if not logs:
        return "(no logs)"

    by_service: dict[str, List[Any]] = defaultdict(list)
    for log in logs:
        by_service[_get(log, "service_name", "service", default="unknown")].append(log)

    # Rank services by worst severity observed, then by count of errors.
    def _service_rank(items: List[Any]) -> tuple[int, int]:
        worst = max(
            (_SEV_RANK.get(str(_get(x, "severity", default="info")).lower(), 0) for x in items),
            default=0,
        )
        errors = sum(
            1 for x in items
            if str(_get(x, "severity", default="info")).lower() in _ERROR_LEVELS
        )
        return (-worst, -errors)

    ordered_services = sorted(by_service.items(), key=lambda kv: _service_rank(kv[1]))
    budget = max_lines
    blocks: List[str] = []

    for service, items in ordered_services:
        if budget <= 0:
            blocks.append(f"(+{sum(len(v) for _, v in ordered_services[len(blocks):])} more logs omitted)")
            break

        # Sort by severity (worst first), then chronologically.
        items_sorted = sorted(
            items,
            key=lambda x: (
                -_SEV_RANK.get(str(_get(x, "severity", default="info")).lower(), 0),
                _get(x, "timestamp", "ts", default=""),
            ),
        )

        # Dedup near-duplicate messages within the service.
        seen: Counter[str] = Counter()
        unique: List[tuple[Any, int]] = []
        if dedup_within_service:
            groups: dict[str, list[Any]] = defaultdict(list)
            for log in items_sorted:
                key = str(_get(log, "message", default=""))[:80]
                groups[key].append(log)
            # Preserve severity/time ordering: iterate items_sorted, emit first of each group.
            emitted: set[str] = set()
            for log in items_sorted:
                key = str(_get(log, "message", default=""))[:80]
                if key in emitted:
                    continue
                emitted.add(key)
                unique.append((log, len(groups[key])))
        else:
            unique = [(log, 1) for log in items_sorted]

        lines: List[str] = [f"[{service}] ({len(items)} logs)"]
        per_service_cap = min(len(unique), budget, 8)
        for log, dup_count in unique[:per_service_cap]:
            ts = _fmt_time_only(_get(log, "timestamp", "ts"))
            sev = str(_get(log, "severity", default="info")).upper()
            msg = str(_get(log, "message", default="")).strip().replace("\n", " ")
            if len(msg) > 220:
                msg = msg[:217] + "..."
            # Emit a stable citable identifier: prefer the DB id when present.
            log_id = _get(log, "id")
            if isinstance(log_id, int):
                ref_tag = f"[log_id={log_id}]"
            else:
                ref_tag = ""
            suffix = f" (x{dup_count - 1} more)" if dup_count > 1 else ""
            prefix = f"- {ref_tag} " if ref_tag else "- "
            lines.append(f"{prefix}{ts} {sev} {msg}{suffix}")
            budget -= 1
            if budget <= 0:
                break

        remaining = len(unique) - per_service_cap
        if remaining > 0:
            lines.append(f"  ... +{remaining} more unique message(s) in {service}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def _format_historical_incidents(incidents: Sequence[Any]) -> str:
    """Render retrieved past incidents as concise prompt context.

    Accepts either `SimilarIncident` dataclass instances (from memory_service)
    or plain mappings with the same keys. Distances are shown as a similarity
    score (1 - distance) when present, which is easier for the model to read.
    """
    if not incidents:
        return "No similar past incidents on record."

    lines: List[str] = [
        f"{len(incidents)} prior incident(s) found in memory, most similar first:"
    ]
    for i, inc in enumerate(incidents, start=1):
        title = _get(inc, "title", default="(untitled)") or "(untitled)"
        severity = str(_get(inc, "severity", default="") or "").lower()
        root_cause = str(_get(inc, "root_cause", default="") or "").strip()
        fix = str(_get(inc, "fix", "suggested_fix", default="") or "").strip()
        distance = _get(inc, "distance")

        header = f"{i}. {title}"
        if severity:
            header += f" [{severity}]"
        if isinstance(distance, (int, float)):
            try:
                # Cosine distance is in [0, 2]; smaller = more similar.
                similarity = max(0.0, 1.0 - float(distance))
                header += f" (similarity={similarity:.2f})"
            except (TypeError, ValueError):
                pass
        lines.append(header)

        if root_cause:
            lines.append(f"   root_cause: {root_cause[:300]}")
        if fix:
            lines.append(f"   fix: {fix[:300]}")

    return "\n".join(lines)


def build_analysis_prompt(
    logs: Sequence[Any],
    anomalies: Sequence[Any],
    historical_incidents: Sequence[Any] = (),
    max_log_lines: int = 25,
) -> str:
    """Build the user-turn prompt for the analysis agent.

    Args:
        logs: Iterable of log entries - either SQLAlchemy `Log` instances
            or dicts with keys {timestamp, service_name, severity, message}.
        anomalies: Iterable of anomaly records - either `Anomaly` dataclasses
            or dicts with keys {kind, service, severity, summary, score,
            evidence_log_ids}.
        historical_incidents: Optional iterable of past incidents retrieved
            from vector memory. Accepts `SimilarIncident` dataclasses OR
            mappings with keys {title, severity, root_cause, fix, distance}.
            When empty/omitted, the historical section is skipped.
        max_log_lines: Soft cap on the number of log excerpt lines included.

    Returns:
        A concise, well-structured user prompt string. Does NOT include the
        system prompt.
    """
    logs = list(logs) if not isinstance(logs, list) else logs
    anomalies = list(anomalies) if not isinstance(anomalies, list) else anomalies
    historical = list(historical_incidents) if historical_incidents else []

    sections = [
        "### Logs summary",
        _summarize_logs(logs),
        "",
        "### Detected anomalies",
        _summarize_anomalies(anomalies),
        "",
    ]

    if historical:
        sections.extend([
            "### Similar past incidents (historical context)",
            _format_historical_incidents(historical),
            "Use these as hints only; confirm against the CURRENT evidence "
            "before reusing a prior root cause or fix.",
            "",
        ])

    sections.extend([
        "### Log excerpts (grouped by service, errors first)",
        "Each line is tagged with [log_id=N] - cite these ids in relevant_log_lines.",
        _format_log_excerpts(logs, max_lines=max_log_lines),
        "",
        "### Task",
        "Diagnose the incident using the data above. "
        "Return ONLY the required JSON object with ALL fields populated: "
        "issue, root_cause, fix, severity, confidence, needs_more_data, "
        "requested_action, requested_action_args, reasoning_steps, "
        "relevant_log_lines. "
        "Show your chain of thought in reasoning_steps (3-7 concise steps) and "
        "cite the specific log_ids that support your diagnosis in "
        "relevant_log_lines.",
    ])
    return "\n".join(sections).strip() + "\n"


__all__ = [
    "SYSTEM_PROMPT",
    "build_user_prompt",
    "build_analysis_prompt",
]
