"""Evaluation service (Plan §10.2).

Scores LLM analyses against the known ground truth of simulated scenarios.
Everything here is deterministic and NLP-free: matching is keyword-based with
explicit thresholds, so the behavior is interpretable and reproducible in CI.

Public API
----------
- `get_ground_truth(scenario_name)`        : return ScenarioGroundTruth or raise.
- `list_ground_truths()`                   : all known scenarios.
- `evaluate_prediction(predicted, truth)`  : pure-function scoring (no DB).
- `evaluate_and_store(db, scenario_name, incident_id, analysis_id=None)`:
     resolve the Analysis row, evaluate, persist, return the Evaluation.
- `summarize(db, scenario_name=None)`      : aggregate metrics incl. calibration.

Scoring model
-------------
For each evaluation we compute three booleans:
  - root_cause_match : predicted root_cause contains >= N required keywords
  - severity_match   : predicted severity is in the accepted severity set
  - fix_match        : predicted fix contains >= M required keywords

`overall_correct` is TRUE iff both root_cause AND severity match (the two
essential dimensions). `score` is a soft weighted blend in [0, 1]:

    score = 0.55 * root_cause_ratio + 0.25 * severity + 0.20 * fix_ratio

where `*_ratio` = min(1.0, keyword_hits / min_required) so extra hits don't
inflate the score beyond 1.0 and the blend always lies in [0, 1].
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import fmean
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.logging import logger
from app.models.analysis import Analysis
from app.models.evaluation import Evaluation
from app.models.incident import Incident
from app.schemas.evaluation import (
    CalibrationStats,
    EvaluationResult,
    EvaluationSummary,
    ScenarioSummary,
)


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioGroundTruth:
    """Canonical 'correct answer' for a simulation scenario.

    Attributes:
        scenario:              Identifier (matches log_generator scenario names).
        reference_root_cause:  Human-readable statement of the true root cause.
        reference_fix:         Human-readable statement of the expected remediation.
        accepted_severities:   Severity values considered correct (broad to allow
                               'high' OR 'critical' for destructive failures).
        root_cause_keywords:   Keyword pool; prediction needs >= min_root_cause.
        min_root_cause:        Threshold of root_cause_keywords that must appear.
        fix_keywords:          Keyword pool for fix matching.
        min_fix:               Threshold for fix_match.
    """

    scenario: str
    reference_root_cause: str
    reference_fix: str
    accepted_severities: FrozenSet[str]
    root_cause_keywords: Tuple[str, ...]
    min_root_cause: int
    fix_keywords: Tuple[str, ...]
    min_fix: int

    @property
    def primary_severity(self) -> str:
        """Return a canonical severity string for storage (the first accepted)."""
        # FrozenSet has no order; pick the highest-severity entry for stability.
        ranking = ["critical", "high", "medium", "low"]
        for sev in ranking:
            if sev in self.accepted_severities:
                return sev
        return "medium"


SCENARIO_GROUND_TRUTH: Dict[str, ScenarioGroundTruth] = {
    "database_failure": ScenarioGroundTruth(
        scenario="database_failure",
        reference_root_cause=(
            "The primary database is unreachable, exhausting the connection "
            "pool and causing cascading 5xx errors from upstream services."
        ),
        reference_fix=(
            "Restore DB connectivity or failover to a replica; increase the "
            "connection pool size and add a circuit breaker on the data path."
        ),
        accepted_severities=frozenset({"high", "critical"}),
        root_cause_keywords=(
            "database", "db", "connection", "pool", "timeout", "unreachable",
        ),
        min_root_cause=3,
        fix_keywords=("pool", "connection", "restart", "scale", "failover", "breaker"),
        min_fix=1,
    ),
    "memory_leak": ScenarioGroundTruth(
        scenario="memory_leak",
        reference_root_cause=(
            "Gradual heap growth on the affected service leads to garbage "
            "collection thrashing and eventual OutOfMemory errors."
        ),
        reference_fix=(
            "Restart the affected service to reclaim memory, then identify "
            "and patch the leak (increase heap temporarily if needed)."
        ),
        accepted_severities=frozenset({"high", "critical"}),
        root_cause_keywords=(
            "memory", "leak", "heap", "oom", "gc", "garbage", "outofmemory",
        ),
        min_root_cause=2,
        fix_keywords=("restart", "heap", "memory", "patch", "redeploy"),
        min_fix=1,
    ),
    "latency_spike": ScenarioGroundTruth(
        scenario="latency_spike",
        reference_root_cause=(
            "A downstream dependency slowed down, causing upstream p99 latency "
            "to spike and request timeouts to accumulate at the gateway."
        ),
        reference_fix=(
            "Add or tighten timeouts, introduce a circuit breaker on the slow "
            "dependency, and scale the affected service horizontally."
        ),
        accepted_severities=frozenset({"medium", "high"}),
        root_cause_keywords=(
            "latency", "slow", "p99", "timeout", "upstream", "downstream",
        ),
        min_root_cause=2,
        fix_keywords=(
            "timeout", "breaker", "scale", "retries", "cache", "throttle",
        ),
        min_fix=1,
    ),
}


def get_ground_truth(scenario_name: str) -> ScenarioGroundTruth:
    """Return the ground truth for a scenario, or raise KeyError."""
    try:
        return SCENARIO_GROUND_TRUTH[scenario_name]
    except KeyError as exc:
        known = ", ".join(sorted(SCENARIO_GROUND_TRUTH))
        raise KeyError(f"Unknown scenario '{scenario_name}'. Known: {known}") from exc


def list_ground_truths() -> List[ScenarioGroundTruth]:
    """All known scenario ground truths."""
    return list(SCENARIO_GROUND_TRUTH.values())


# ---------------------------------------------------------------------------
# Pure scoring (DB-free, fully unit-testable)
# ---------------------------------------------------------------------------


_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> List[str]:
    """Lowercase word tokenizer. Good enough for keyword containment."""
    return _WORD_RE.findall((text or "").lower())


def _count_keyword_hits(
    prediction: str, keywords: Tuple[str, ...]
) -> Tuple[List[str], List[str]]:
    """Return (matched, missing) keyword lists. Matching is substring-safe:
    multi-word keywords are matched as whole phrases; single words match as
    standalone tokens (not as substrings of longer words).
    """
    text = (prediction or "").lower()
    tokens = set(_tokenize(text))
    matched: List[str] = []
    missing: List[str] = []
    for kw in keywords:
        kw_lower = kw.lower().strip()
        if not kw_lower:
            continue
        hit = (
            # Phrase keyword -> substring check.
            (" " in kw_lower and kw_lower in text)
            # Single-word keyword -> whole-token match.
            or (" " not in kw_lower and kw_lower in tokens)
        )
        if hit:
            matched.append(kw)
        else:
            missing.append(kw)
    return matched, missing


def evaluate_prediction(
    predicted: Dict[str, Any],
    truth: ScenarioGroundTruth,
) -> EvaluationResult:
    """Score one prediction against a scenario ground truth.

    `predicted` is a dict with at minimum: root_cause, severity, fix, confidence.
    Accepts either a plain dict or an `LLMStructuredOutput.model_dump()` payload.
    """
    predicted_root_cause = str(predicted.get("root_cause") or "")
    predicted_severity = str(predicted.get("severity") or "").lower().strip()
    predicted_fix = str(predicted.get("fix") or "")
    confidence = float(predicted.get("confidence") or 0.0)
    confidence = max(0.0, min(1.0, confidence))

    # Root cause keyword matching.
    rc_matched, rc_missing = _count_keyword_hits(
        predicted_root_cause, truth.root_cause_keywords
    )
    root_cause_match = len(rc_matched) >= truth.min_root_cause

    # Fix keyword matching.
    fix_matched, _fix_missing = _count_keyword_hits(predicted_fix, truth.fix_keywords)
    fix_match = len(fix_matched) >= truth.min_fix

    # Severity is a direct lookup.
    severity_match = predicted_severity in truth.accepted_severities

    # Ratios (capped at 1.0 so extra hits don't inflate past perfect).
    rc_ratio = min(1.0, len(rc_matched) / max(truth.min_root_cause, 1))
    fix_ratio = min(1.0, len(fix_matched) / max(truth.min_fix, 1))

    score = 0.55 * rc_ratio + 0.25 * (1.0 if severity_match else 0.0) + 0.20 * fix_ratio
    score = max(0.0, min(1.0, score))

    keyword_coverage = (
        len(rc_matched) / len(truth.root_cause_keywords)
        if truth.root_cause_keywords
        else 0.0
    )

    overall_correct = root_cause_match and severity_match

    return EvaluationResult(
        scenario_name=truth.scenario,
        expected_root_cause=truth.reference_root_cause,
        expected_severity=truth.primary_severity,
        expected_fix=truth.reference_fix,
        predicted_root_cause=predicted_root_cause,
        predicted_severity=predicted_severity or "unknown",
        predicted_fix=predicted_fix,
        confidence=confidence,
        root_cause_match=root_cause_match,
        severity_match=severity_match,
        fix_match=fix_match,
        overall_correct=overall_correct,
        score=score,
        keyword_coverage=keyword_coverage,
        matched_keywords=rc_matched,
        missing_keywords=rc_missing,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


@dataclass
class _ResolvedTarget:
    incident_id: int
    analysis: Analysis


def _resolve_target(
    db: Session, incident_id: int, analysis_id: Optional[int] = None
) -> _ResolvedTarget:
    """Locate the Analysis row to grade, with friendly errors."""
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise LookupError(f"Incident id={incident_id} not found")

    if analysis_id is not None:
        analysis = db.get(Analysis, analysis_id)
        if analysis is None or analysis.incident_id != incident_id:
            raise LookupError(
                f"Analysis id={analysis_id} does not belong to incident {incident_id}"
            )
        return _ResolvedTarget(incident_id=incident_id, analysis=analysis)

    # Default: latest analysis by created_at / id.
    analyses = sorted(
        incident.analyses or [],
        key=lambda a: (a.created_at or a.id, a.id),
    )
    if not analyses:
        raise LookupError(f"Incident id={incident_id} has no analyses to evaluate")
    return _ResolvedTarget(incident_id=incident_id, analysis=analyses[-1])


def evaluate_and_store(
    db: Session,
    scenario_name: str,
    incident_id: int,
    analysis_id: Optional[int] = None,
) -> Evaluation:
    """Evaluate the chosen analysis against the scenario and persist the result.

    Raises:
        KeyError:   scenario_name is not a known ground truth.
        LookupError: incident / analysis not found or mismatched.
    """
    truth = get_ground_truth(scenario_name)
    target = _resolve_target(db, incident_id, analysis_id)

    predicted_payload: Dict[str, Any] = target.analysis.structured_output or {}
    result = evaluate_prediction(predicted_payload, truth)

    row = Evaluation(
        scenario_name=truth.scenario,
        incident_id=target.incident_id,
        analysis_id=target.analysis.id,
        expected_root_cause=result.expected_root_cause,
        expected_severity=result.expected_severity,
        expected_fix=result.expected_fix,
        predicted_root_cause=result.predicted_root_cause,
        predicted_severity=result.predicted_severity,
        predicted_fix=result.predicted_fix,
        confidence=result.confidence,
        root_cause_match=result.root_cause_match,
        severity_match=result.severity_match,
        fix_match=result.fix_match,
        overall_correct=result.overall_correct,
        score=result.score,
        keyword_coverage=result.keyword_coverage,
        matched_keywords=list(result.matched_keywords),
        missing_keywords=list(result.missing_keywords),
        predicted_output=predicted_payload or None,
    )

    db.add(row)
    db.commit()
    db.refresh(row)

    logger.info(
        "evaluation stored: scenario={} incident_id={} analysis_id={} "
        "correct={} score={:.2f} confidence={:.2f}",
        truth.scenario,
        incident_id,
        target.analysis.id,
        row.overall_correct,
        row.score,
        row.confidence,
    )
    return row


# ---------------------------------------------------------------------------
# Aggregation / calibration
# ---------------------------------------------------------------------------


@dataclass
class _SummaryAccumulator:
    total: int = 0
    correct: int = 0
    rc_correct: int = 0
    sev_correct: int = 0
    fix_correct: int = 0
    confidences: List[float] = field(default_factory=list)
    scores: List[float] = field(default_factory=list)
    conf_when_correct: List[float] = field(default_factory=list)
    conf_when_incorrect: List[float] = field(default_factory=list)

    def add(self, row: Evaluation) -> None:
        self.total += 1
        if row.overall_correct:
            self.correct += 1
            self.conf_when_correct.append(row.confidence)
        else:
            self.conf_when_incorrect.append(row.confidence)
        self.rc_correct += int(bool(row.root_cause_match))
        self.sev_correct += int(bool(row.severity_match))
        self.fix_correct += int(bool(row.fix_match))
        self.confidences.append(row.confidence)
        self.scores.append(row.score)


def _safe_mean(values: List[float]) -> float:
    return float(fmean(values)) if values else 0.0


def _safe_ratio(num: int, den: int) -> float:
    return float(num) / float(den) if den > 0 else 0.0


def summarize(
    db: Session, scenario_name: Optional[str] = None
) -> EvaluationSummary:
    """Aggregate accuracy + confidence metrics across evaluations.

    Args:
        scenario_name: If set, aggregate only rows for this scenario. Per-scenario
            breakdown in the response will contain just that one entry.
    """
    query = db.query(Evaluation)
    if scenario_name is not None:
        get_ground_truth(scenario_name)  # validate name (raises KeyError if unknown)
        query = query.filter(Evaluation.scenario_name == scenario_name)

    rows: List[Evaluation] = query.all()

    total_acc = _SummaryAccumulator()
    per_scenario: Dict[str, _SummaryAccumulator] = {}

    for row in rows:
        total_acc.add(row)
        per_scenario.setdefault(row.scenario_name, _SummaryAccumulator()).add(row)

    calibration = CalibrationStats(
        mean_confidence_when_correct=(
            _safe_mean(total_acc.conf_when_correct) if total_acc.conf_when_correct else None
        ),
        mean_confidence_when_incorrect=(
            _safe_mean(total_acc.conf_when_incorrect)
            if total_acc.conf_when_incorrect
            else None
        ),
    )
    if (
        calibration.mean_confidence_when_correct is not None
        and calibration.mean_confidence_when_incorrect is not None
    ):
        calibration.gap = (
            calibration.mean_confidence_when_correct
            - calibration.mean_confidence_when_incorrect
        )

    breakdown: List[ScenarioSummary] = []
    for name in sorted(per_scenario):
        acc = per_scenario[name]
        breakdown.append(
            ScenarioSummary(
                scenario_name=name,
                total=acc.total,
                accuracy=_safe_ratio(acc.correct, acc.total),
                mean_confidence=_safe_mean(acc.confidences),
                mean_score=_safe_mean(acc.scores),
                root_cause_accuracy=_safe_ratio(acc.rc_correct, acc.total),
                severity_accuracy=_safe_ratio(acc.sev_correct, acc.total),
                fix_accuracy=_safe_ratio(acc.fix_correct, acc.total),
            )
        )

    return EvaluationSummary(
        total=total_acc.total,
        accuracy=_safe_ratio(total_acc.correct, total_acc.total),
        mean_confidence=_safe_mean(total_acc.confidences),
        mean_score=_safe_mean(total_acc.scores),
        calibration=calibration,
        by_scenario=breakdown,
    )


__all__ = [
    "ScenarioGroundTruth",
    "SCENARIO_GROUND_TRUTH",
    "get_ground_truth",
    "list_ground_truths",
    "evaluate_prediction",
    "evaluate_and_store",
    "summarize",
]
