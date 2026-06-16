#!/usr/bin/env python
"""Offline evaluation harness for the OpsPilot-AI agent.

Runs the multi-step agent loop against each seeded failure scenario, scores the
result with the deterministic keyword/severity evaluator, and prints an accuracy
+ calibration summary. Exits non-zero when overall accuracy falls below
``--threshold`` so it can act as a regression gate in CI.

This script talks to a real LLM provider (selected via ``LLM_PROVIDER`` /
``LLM_MODEL`` and the matching API key), so it needs a key in the environment.
The vector-memory subsystem is disabled here so the harness is hermetic (no
Chroma store, no embedding-model download).

Usage
-----
    # from the backend/ directory, with an API key exported:
    python scripts/run_eval.py
    python scripts/run_eval.py --scenarios latency_spike,memory_leak --seeds 1,2,3
    python scripts/run_eval.py --threshold 0.8 --json-out eval-report.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

# --- Make `import app` work regardless of how the script is invoked. ----------
_BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


@dataclass
class _EvalLog:
    """Minimal Log-shaped object (the agent + detector only read these fields)."""

    id: int
    timestamp: datetime
    service_name: str
    severity: str
    message: str


def _disable_memory() -> None:
    """Install a no-op memory service so the harness never touches Chroma."""
    from app.services import memory_service

    class _DisabledMemoryService:
        enabled = False

        def store_incident(self, incident, logs=None) -> bool:  # noqa: ANN001, ARG002
            return False

        def retrieve_similar_incidents(self, logs, n_results: int = 3):  # noqa: ANN001, ARG002
            return []

        def reset(self) -> None:
            return None

    memory_service.set_memory_service(_DisabledMemoryService())  # type: ignore[arg-type]


def _materialize_logs(entries: List[Any]) -> List[_EvalLog]:
    """Attach stable integer ids to generated LogCreate entries."""
    logs: List[_EvalLog] = []
    for i, entry in enumerate(entries, start=1):
        logs.append(
            _EvalLog(
                id=i,
                timestamp=entry.timestamp,
                service_name=entry.service_name,
                severity=entry.severity,
                message=entry.message,
            )
        )
    return logs


@dataclass
class _RunOutcome:
    scenario: str
    seed: int
    correct: bool
    score: float
    confidence: float
    predicted_severity: str
    expected_severity: str
    root_cause_match: bool
    severity_match: bool
    fix_match: bool
    iterations: int
    error: Optional[str] = None


def _run_one(scenario: str, seed: int, max_steps: int) -> _RunOutcome:
    from app.agent.orchestrator import run_agent_loop
    from app.services.anomaly_detector import detect_anomalies
    from app.services.evaluation_service import evaluate_prediction, get_ground_truth
    from app.services.log_generator import generate_scenario

    truth = get_ground_truth(scenario)
    entries = generate_scenario(scenario, seed=seed)
    logs = _materialize_logs(entries)
    anomalies = detect_anomalies(logs)  # type: ignore[arg-type]

    run = run_agent_loop(logs, anomalies, max_iterations=max_steps)  # type: ignore[arg-type]
    predicted: Dict[str, Any] = run.final.model_dump(mode="json")
    result = evaluate_prediction(predicted, truth)

    return _RunOutcome(
        scenario=scenario,
        seed=seed,
        correct=result.overall_correct,
        score=result.score,
        confidence=result.confidence,
        predicted_severity=result.predicted_severity,
        expected_severity=result.expected_severity,
        root_cause_match=result.root_cause_match,
        severity_match=result.severity_match,
        fix_match=result.fix_match,
        iterations=run.iterations,
    )


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _print_table(outcomes: List[_RunOutcome]) -> None:
    header = (
        f"{'scenario':<18}{'seed':>5}{'correct':>9}{'score':>7}"
        f"{'conf':>6}{'rc':>4}{'sev':>4}{'fix':>4}{'iters':>6}"
    )
    print(header)
    print("-" * len(header))
    for o in sorted(outcomes, key=lambda x: (x.scenario, x.seed)):
        if o.error:
            print(f"{o.scenario:<18}{o.seed:>5}   ERROR: {o.error}")
            continue
        print(
            f"{o.scenario:<18}{o.seed:>5}{('YES' if o.correct else 'no'):>9}"
            f"{o.score:>7.2f}{o.confidence:>6.2f}"
            f"{('Y' if o.root_cause_match else '-'):>4}"
            f"{('Y' if o.severity_match else '-'):>4}"
            f"{('Y' if o.fix_match else '-'):>4}{o.iterations:>6}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="OpsPilot-AI agent eval harness")
    parser.add_argument(
        "--scenarios",
        default="database_failure,memory_leak,latency_spike",
        help="Comma-separated scenario names.",
    )
    parser.add_argument(
        "--seeds",
        default="1,2,3",
        help="Comma-separated integer seeds (one agent run per scenario x seed).",
    )
    parser.add_argument(
        "--max-steps", type=int, default=3, help="Max agent loop iterations."
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.8,
        help="Minimum overall accuracy required to pass (0..1).",
    )
    parser.add_argument(
        "--json-out", default=None, help="Optional path to write a JSON report."
    )
    args = parser.parse_args()

    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    try:
        seeds = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]
    except ValueError:
        print("error: --seeds must be comma-separated integers", file=sys.stderr)
        return 2

    _disable_memory()

    outcomes: List[_RunOutcome] = []
    hard_failure = False
    print(
        f"\nRunning eval: {len(scenarios)} scenario(s) x {len(seeds)} seed(s) "
        f"= {len(scenarios) * len(seeds)} agent run(s)\n"
    )
    for scenario in scenarios:
        for seed in seeds:
            try:
                outcomes.append(_run_one(scenario, seed, args.max_steps))
            except Exception as exc:  # noqa: BLE001 - surface any provider/setup error
                hard_failure = True
                outcomes.append(
                    _RunOutcome(
                        scenario=scenario,
                        seed=seed,
                        correct=False,
                        score=0.0,
                        confidence=0.0,
                        predicted_severity="error",
                        expected_severity="",
                        root_cause_match=False,
                        severity_match=False,
                        fix_match=False,
                        iterations=0,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )

    _print_table(outcomes)

    scored = [o for o in outcomes if o.error is None]
    total = len(scored)
    correct = sum(1 for o in scored if o.correct)
    accuracy = correct / total if total else 0.0

    conf_correct = _mean([o.confidence for o in scored if o.correct])
    conf_incorrect = _mean([o.confidence for o in scored if not o.correct])

    per_scenario: Dict[str, Dict[str, float]] = {}
    for scenario in scenarios:
        rows = [o for o in scored if o.scenario == scenario]
        if rows:
            per_scenario[scenario] = {
                "accuracy": sum(1 for r in rows if r.correct) / len(rows),
                "mean_score": _mean([r.score for r in rows]),
                "mean_confidence": _mean([r.confidence for r in rows]),
                "n": len(rows),
            }

    print("\n=== Summary ===")
    print(f"runs scored      : {total} (errors: {len(outcomes) - total})")
    print(f"overall accuracy : {accuracy:.0%}  ({correct}/{total})")
    print(f"mean score       : {_mean([o.score for o in scored]):.2f}")
    print(
        "calibration      : "
        f"conf|correct={conf_correct:.2f}  conf|incorrect={conf_incorrect:.2f}  "
        f"gap={conf_correct - conf_incorrect:+.2f}"
    )
    for scenario, stats in per_scenario.items():
        print(
            f"  - {scenario:<18} acc={stats['accuracy']:.0%} "
            f"score={stats['mean_score']:.2f} conf={stats['mean_confidence']:.2f} "
            f"(n={int(stats['n'])})"
        )

    report = {
        "accuracy": accuracy,
        "threshold": args.threshold,
        "runs_scored": total,
        "runs_correct": correct,
        "mean_score": _mean([o.score for o in scored]),
        "calibration": {
            "mean_confidence_when_correct": conf_correct,
            "mean_confidence_when_incorrect": conf_incorrect,
            "gap": conf_correct - conf_incorrect,
        },
        "by_scenario": per_scenario,
        "runs": [vars(o) for o in outcomes],
    }
    if args.json_out:
        pathlib.Path(args.json_out).write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        print(f"\nwrote JSON report -> {args.json_out}")

    if hard_failure:
        print("\nFAIL: one or more runs errored out (provider/setup problem).")
        return 2
    if accuracy < args.threshold:
        print(
            f"\nFAIL: accuracy {accuracy:.0%} is below the "
            f"{args.threshold:.0%} regression threshold."
        )
        return 1

    print(f"\nPASS: accuracy {accuracy:.0%} >= threshold {args.threshold:.0%}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
