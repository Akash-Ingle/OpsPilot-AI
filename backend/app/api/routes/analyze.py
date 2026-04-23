"""Routes for triggering agent analysis."""

import json
from typing import List

from fastapi import APIRouter, HTTPException, status

from app.agent.llm_client import LLMError, LLMTimeoutError, LLMValidationError
from app.agent.orchestrator import run_agent_loop
from app.api.deps import DBSession
from app.core.logging import logger
from app.models.analysis import Analysis
from app.models.incident import Incident
from app.models.log import Log
from app.schemas.analysis import AnalyzeRequest, AnalyzeResponse
from app.services import memory_service
from app.services.anomaly_detector import detect_anomalies

router = APIRouter()


@router.post(
    "",
    response_model=AnalyzeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run a multi-step agent analysis over recent logs",
)
def trigger_analysis(payload: AnalyzeRequest, db: DBSession) -> AnalyzeResponse:
    """Analyze the most recent logs, detect anomalies, run the multi-step agent
    loop (with tool dispatch), persist an incident + analysis, and return the
    structured result together with end-to-end observability.
    """
    # 1. Fetch recent logs from DB.
    query = db.query(Log)
    if payload.service_name:
        query = query.filter(Log.service_name == payload.service_name)
    logs: List[Log] = (
        query.order_by(Log.timestamp.desc()).limit(payload.limit).all()
    )
    # Analyze in chronological order.
    logs.reverse()

    if not logs:
        logger.info("analyze: no logs available to analyze (filter={})", payload.service_name)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No logs available to analyze. Upload logs first via /logs/upload.",
        )

    logger.info(
        "analyze: fetched {} log(s) for analysis (service_filter={})",
        len(logs),
        payload.service_name or "*",
    )

    # 2. Run anomaly detector.
    anomalies = detect_anomalies(logs)
    logger.info("analyze: detected {} anomaly signal(s)", len(anomalies))

    # 3. Call the agent (multi-step, with tool dispatch).
    try:
        run = run_agent_loop(logs, anomalies, max_iterations=payload.max_steps)
    except LLMTimeoutError as exc:
        logger.error("analyze: LLM call timed out: {}", exc)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="LLM provider timed out. Please retry.",
        ) from exc
    except LLMValidationError as exc:
        logger.error("analyze: LLM returned invalid structured output: {}", exc.errors)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM returned an invalid response after retries.",
        ) from exc
    except LLMError as exc:
        logger.error("analyze: LLM call failed: {}", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM call failed: {exc}",
        ) from exc

    result = run.final
    structured = result.model_dump(mode="json")
    observability = run.observability
    # `run_agent_loop` always populates observability, but guard defensively so
    # a future refactor that forgets this can't crash the route.
    observability_payload = (
        observability.model_dump(mode="json") if observability is not None else None
    )

    # 4-5. Persist incident + analysis atomically.
    try:
        incident = Incident(
            title=(result.issue or "Unclassified incident")[:255],
            severity=result.severity,
            root_cause=result.root_cause,
            suggested_fix=result.fix,
        )
        db.add(incident)
        db.flush()  # populate incident.id without committing

        analysis = Analysis(
            incident_id=incident.id,
            llm_output=json.dumps(structured, ensure_ascii=False),
            structured_output=structured,
            confidence_score=float(result.confidence),
            step_index=max(run.iterations - 1, 0),
            observability=observability_payload,
        )
        db.add(analysis)
        db.commit()
        db.refresh(incident)
        db.refresh(analysis)
    except Exception as exc:  # pragma: no cover - defensive
        db.rollback()
        logger.exception("analyze: failed to persist incident/analysis: {}", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist analysis results.",
        ) from exc

    logger.info(
        "analyze: created incident_id={} analysis_id={} severity={} confidence={:.2f} "
        "iterations={} tools={} duration_ms={:.1f} stopped_reason={}",
        incident.id,
        analysis.id,
        result.severity.value if hasattr(result.severity, "value") else result.severity,
        float(result.confidence),
        run.iterations,
        len(observability.tools_called) if observability else 0,
        observability.duration_ms if observability else 0.0,
        observability.stopped_reason if observability else "unknown",
    )

    # 6. Best-effort: store the incident in vector memory for future retrieval.
    # Failures are logged inside memory_service and must not affect the response.
    try:
        memory_service.store_incident(incident, logs=logs)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("analyze: memory store_incident failed: {}", exc)

    # 7. Return clean structured response.
    if observability is None:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent run produced no observability payload.",
        )

    return AnalyzeResponse(
        incident_id=incident.id,
        analysis_id=analysis.id,
        steps_run=run.iterations,
        logs_analyzed=len(logs),
        anomalies_detected=len(anomalies),
        final=result,
        observability=observability,
    )
