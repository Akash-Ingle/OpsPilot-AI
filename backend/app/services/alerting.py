"""Outbound incident alerting (Slack incoming webhooks).

Posts a formatted message to a project's Slack webhook when an incident is
opened. All failures are swallowed and logged - alerting must never break the
ingestion/analysis path.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from app.config import settings
from app.core.logging import logger
from app.models.incident import Incident
from app.schemas.analysis import LLMStructuredOutput

_SEVERITY_EMOJI = {
    "critical": ":rotating_light:",
    "high": ":warning:",
    "medium": ":large_yellow_circle:",
    "low": ":information_source:",
}


def _sev(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def build_slack_payload(
    incident: Incident,
    result: LLMStructuredOutput,
    *,
    similar_summary: Optional[str] = None,
    served_from_cache: bool = False,
) -> dict:
    """Build a Slack Block Kit payload summarizing the incident."""
    severity = _sev(result.severity)
    emoji = _SEVERITY_EMOJI.get(severity, ":mag:")
    confidence_pct = f"{float(result.confidence) * 100:.0f}%"

    title = result.issue or incident.title or "Incident detected"
    header = f"{emoji} OpsPilot incident: {title}"[:150]

    fields = [
        {"type": "mrkdwn", "text": f"*Severity:*\n{severity}"},
        {"type": "mrkdwn", "text": f"*Confidence:*\n{confidence_pct}"},
    ]

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": header, "emoji": True}},
        {"type": "section", "fields": fields},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Root cause*\n{result.root_cause}"[:2900]},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Suggested fix*\n{result.fix}"[:2900]},
        },
    ]

    if similar_summary:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Similar past incident*\n{similar_summary}"[:2900]},
            }
        )

    context_bits = []
    if served_from_cache:
        context_bits.append("served from cached analysis (LLM quota)")
    base = settings.frontend_base_url.rstrip("/")
    if base:
        link = f"{base}/incidents/{incident.id}"
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View in OpsPilot"},
                        "url": link,
                    }
                ],
            }
        )
    if context_bits:
        blocks.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(context_bits)}]}
        )

    return {"text": header, "blocks": blocks}


def send_slack_test_message(webhook_url: str) -> bool:
    """Post a simple confirmation message so a user can verify their webhook
    works without waiting for a real incident. Returns success."""
    payload = {
        "text": ":white_check_mark: OpsPilot test alert",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": ":white_check_mark: OpsPilot is connected",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "This is a test alert. When OpsPilot opens a real incident, "
                        "the severity, root cause, suggested fix, and a link to the "
                        "full analysis will be posted here."
                    ),
                },
            },
        ],
    }
    try:
        resp = httpx.post(webhook_url, json=payload, timeout=10.0)
        if resp.status_code >= 300:
            logger.warning(
                "alerting: Slack test webhook returned {} - {}",
                resp.status_code,
                resp.text[:200],
            )
            return False
        logger.info("alerting: posted Slack test alert")
        return True
    except Exception as exc:  # pragma: no cover - network defensive
        logger.warning("alerting: failed to post Slack test alert: {}", exc)
        return False


def send_slack_incident_alert(
    webhook_url: str,
    incident: Incident,
    result: LLMStructuredOutput,
    *,
    similar_summary: Optional[str] = None,
    served_from_cache: bool = False,
) -> bool:
    """POST the incident alert to a Slack incoming webhook. Returns success."""
    payload = build_slack_payload(
        incident,
        result,
        similar_summary=similar_summary,
        served_from_cache=served_from_cache,
    )
    try:
        resp = httpx.post(webhook_url, json=payload, timeout=10.0)
        if resp.status_code >= 300:
            logger.warning(
                "alerting: Slack webhook returned {} - {}", resp.status_code, resp.text[:200]
            )
            return False
        logger.info("alerting: posted Slack alert for incident_id={}", incident.id)
        return True
    except Exception as exc:  # pragma: no cover - network defensive
        logger.warning("alerting: failed to post Slack alert: {}", exc)
        return False


__all__ = [
    "build_slack_payload",
    "send_slack_incident_alert",
    "send_slack_test_message",
]
