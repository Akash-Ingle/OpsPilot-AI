"""Always-on watcher: turn freshly ingested logs into incidents automatically.

When a project ships logs to ``/ingest``, the route schedules
``auto_analyze_project`` as a background task. The watcher detects anomalies over
the project's recent logs and, if something looks wrong (and the project isn't in
its cooldown window), runs the agent, opens an incident, and fires a Slack alert.

This is the piece that makes OpsPilot *proactive* rather than a paste-into-chat
tool: nobody has to ask - it watches and tells you.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional

from app.agent.demo_cache import cached_run_for_logs
from app.agent.llm_client import LLMError, LLMTimeoutError, LLMValidationError
from app.agent.orchestrator import AgentRunResult, run_agent_loop
from app.config import settings
from app.core.logging import logger
from app.core.metrics import record_analysis, record_incident
from app.database import SessionLocal
from app.models.analysis import Analysis
from app.models.incident import Incident
from app.models.log import Log
from app.models.project import Project
from app.services import memory_service
from app.services.anomaly_detector import detect_anomalies


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _in_cooldown(project: Project) -> bool:
    last = project.last_auto_analysis_at
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed = (_now() - last).total_seconds()
    return elapsed < settings.auto_analyze_cooldown_seconds


def _similar_summary(logs: List[Log]) -> Optional[str]:
    try:
        similar = memory_service.retrieve_similar_incidents(logs, n_results=1)
    except Exception:  # pragma: no cover - defensive
        return None
    if not similar:
        return None
    top = similar[0]
    title = getattr(top, "title", None) or "previous incident"
    root = getattr(top, "root_cause", None) or ""
    return f"{title} — {root}"[:280]


def _run_agent(logs, anomalies) -> tuple[AgentRunResult, bool]:
    """Run the agent loop, falling back to a cached analysis on LLM failure."""
    try:
        return run_agent_loop(logs, anomalies, max_iterations=4), False
    except (LLMError, LLMTimeoutError, LLMValidationError) as exc:
        cached = cached_run_for_logs(logs) if settings.demo_cache_enabled else None
        if cached is None:
            raise
        logger.warning("watcher: live LLM unavailable ({}); using cached analysis", exc)
        return cached, True


def auto_analyze_project(project_id: int) -> Optional[int]:
    """Detect anomalies for a project's recent logs and, if warranted, open an
    incident + alert. Returns the new incident id, or None if nothing was done.

    Runs in its own DB session (it is invoked as a FastAPI background task after
    the ingest response has been sent). Never raises.
    """
    if not settings.auto_analyze_enabled:
        return None

    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if project is None:
            return None
        if _in_cooldown(project):
            logger.info("watcher: project_id={} in cooldown; skipping", project_id)
            return None

        logs: List[Log] = (
            db.query(Log)
            .filter(Log.project_id == project_id)
            .order_by(Log.timestamp.desc())
            .limit(settings.auto_analyze_window)
            .all()
        )
        logs.reverse()
        if not logs:
            return None

        anomalies = detect_anomalies(logs)
        if not anomalies:
            logger.info("watcher: project_id={} no anomalies; skipping", project_id)
            return None

        logger.info(
            "watcher: project_id={} {} anomaly signal(s); running agent",
            project_id,
            len(anomalies),
        )

        try:
            run, served_from_cache = _run_agent(logs, anomalies)
        except (LLMError, LLMTimeoutError, LLMValidationError) as exc:
            logger.error("watcher: analysis failed for project_id={}: {}", project_id, exc)
            return None

        result = run.final
        structured = result.model_dump(mode="json")
        observability = (
            run.observability.model_dump(mode="json") if run.observability else None
        )

        incident = Incident(
            project_id=project_id,
            title=(result.issue or "Unclassified incident")[:255],
            severity=result.severity,
            root_cause=result.root_cause,
            suggested_fix=result.fix,
        )
        db.add(incident)
        db.flush()

        analysis = Analysis(
            incident_id=incident.id,
            llm_output=json.dumps(structured, ensure_ascii=False),
            structured_output=structured,
            confidence_score=float(result.confidence),
            step_index=max(run.iterations - 1, 0),
            observability=observability,
        )
        db.add(analysis)
        project.last_auto_analysis_at = _now()
        db.commit()
        db.refresh(incident)

        record_incident("watcher")
        record_analysis(served_from_cache)

        logger.info(
            "watcher: opened incident_id={} (project_id={} severity={} cached={})",
            incident.id,
            project_id,
            result.severity.value if hasattr(result.severity, "value") else result.severity,
            served_from_cache,
        )

        # Best-effort memory store (after computing similar so we don't match self).
        similar_summary = _similar_summary(logs)
        try:
            memory_service.store_incident(incident, logs=logs)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("watcher: memory store failed: {}", exc)

        # Best-effort Slack alert.
        if project.alerts_enabled and project.slack_webhook_url:
            from app.services.alerting import send_slack_incident_alert

            send_slack_incident_alert(
                project.slack_webhook_url,
                incident,
                result,
                similar_summary=similar_summary,
                served_from_cache=served_from_cache,
            )

        return incident.id
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        logger.exception("watcher: unexpected failure for project_id={}: {}", project_id, exc)
        try:
            db.rollback()
        except Exception:
            pass
        return None
    finally:
        db.close()


__all__ = ["auto_analyze_project"]
