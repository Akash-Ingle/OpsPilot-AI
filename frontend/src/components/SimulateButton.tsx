"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  listScenarios,
  simulateScenario,
  triggerAnalysis,
} from "@/lib/api";
import { classNames } from "@/lib/format";
import type { ScenarioInfo } from "@/lib/types";

// Used until the live list loads (and as an offline fallback).
const FALLBACK_SCENARIOS: ScenarioInfo[] = [
  {
    name: "database_failure",
    description:
      "Primary DB becomes unreachable; orders-svc and api-gateway log cascading timeouts and 5xx.",
    default_duration_min: 10,
    default_service: "orders-svc",
  },
  {
    name: "memory_leak",
    description: "inventory-svc heap grows until GC thrash and an OOM crash.",
    default_duration_min: 30,
    default_service: "inventory-svc",
  },
  {
    name: "latency_spike",
    description:
      "checkout-svc p99 latency climbs from ~80ms to >2000ms with upstream timeouts.",
    default_duration_min: 15,
    default_service: "checkout-svc",
  },
];

type Phase = "idle" | "simulating" | "analyzing" | "error";

const PRETTY: Record<string, string> = {
  database_failure: "Database failure",
  memory_leak: "Memory leak",
  latency_spike: "Latency spike",
};

function prettyName(name: string): string {
  return PRETTY[name] ?? name.replace(/_/g, " ");
}

export function SimulateButton() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>(FALLBACK_SCENARIOS);
  const [phase, setPhase] = useState<Phase>("idle");
  const [active, setActive] = useState<ScenarioInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  const busy = phase === "simulating" || phase === "analyzing";

  // Load the live scenario list when the modal opens.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    listScenarios()
      .then((s) => {
        if (!cancelled && Array.isArray(s) && s.length) setScenarios(s);
      })
      .catch(() => {
        /* keep fallback list */
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  // Esc to close (when not mid-run).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) closeModal();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, busy]);

  const run = useCallback(
    async (scenario: ScenarioInfo) => {
      setActive(scenario);
      setError(null);
      try {
        setPhase("simulating");
        await simulateScenario({ scenario: scenario.name });

        setPhase("analyzing");
        const result = await triggerAnalysis({
          service_name: scenario.default_service,
          limit: 200,
          max_steps: 4,
        });

        // Land on the freshly-created incident with its full reasoning trace.
        router.push(`/incidents/${result.incident_id}`);
        router.refresh();
      } catch (err) {
        setPhase("error");
        setError(
          err instanceof ApiError
            ? `${err.message}${err.status ? ` (HTTP ${err.status})` : ""}`
            : (err as Error).message,
        );
      }
    },
    [router],
  );

  function closeModal() {
    if (busy) return;
    setOpen(false);
    setPhase("idle");
    setError(null);
    setActive(null);
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-br from-sky-500 to-indigo-500 px-3.5 py-2 text-sm font-semibold text-white shadow-lg shadow-indigo-500/20 transition-transform hover:scale-[1.02] active:scale-100"
      >
        <svg
          viewBox="0 0 24 24"
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M5 3l14 9-14 9V3z" />
        </svg>
        Simulate incident
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Simulate an incident"
        >
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={closeModal}
          />
          <div className="card relative z-10 w-full max-w-lg p-6 shadow-2xl">
            {busy ? (
              <RunningView phase={phase} scenario={active} />
            ) : (
              <ChooseView
                scenarios={scenarios}
                error={error}
                onPick={run}
                onClose={closeModal}
              />
            )}
          </div>
        </div>
      )}
    </>
  );
}

function ChooseView({
  scenarios,
  error,
  onPick,
  onClose,
}: {
  scenarios: ScenarioInfo[];
  error: string | null;
  onPick: (s: ScenarioInfo) => void;
  onClose: () => void;
}) {
  return (
    <>
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold text-neutral-50">
            Simulate an incident
          </h2>
          <p className="mt-1 text-sm text-neutral-400">
            Pick a failure scenario. OpsPilot will generate realistic logs, then
            run the AI agent to diagnose it end-to-end.
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1 text-neutral-500 transition-colors hover:bg-white/5 hover:text-neutral-300"
          aria-label="Close"
        >
          <svg
            viewBox="0 0 24 24"
            className="h-5 w-5"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      {error && (
        <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/[0.06] px-3 py-2 text-sm text-red-200">
          {error}
        </div>
      )}

      <div className="space-y-2">
        {scenarios.map((s) => (
          <button
            key={s.name}
            type="button"
            onClick={() => onPick(s)}
            className="card card-hover group flex w-full items-center gap-3 p-3.5 text-left"
          >
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-white/[0.04] text-neutral-300 group-hover:text-sky-300">
              <ScenarioIcon name={s.name} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2">
                <span className="text-sm font-semibold text-neutral-100">
                  {prettyName(s.name)}
                </span>
                <span className="kbd">{s.default_service}</span>
              </span>
              <span className="mt-0.5 block text-xs leading-relaxed text-neutral-400">
                {s.description}
              </span>
            </span>
            <svg
              viewBox="0 0 24 24"
              className="h-4 w-4 shrink-0 text-neutral-600 transition-colors group-hover:text-neutral-300"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M9 18l6-6-6-6" />
            </svg>
          </button>
        ))}
      </div>
    </>
  );
}

function RunningView({
  phase,
  scenario,
}: {
  phase: Phase;
  scenario: ScenarioInfo | null;
}) {
  const steps = [
    {
      key: "simulating",
      label: "Generating synthetic logs",
      done: phase === "analyzing",
      active: phase === "simulating",
    },
    {
      key: "analyzing",
      label: "Detecting anomalies & running the AI agent",
      done: false,
      active: phase === "analyzing",
    },
  ];

  return (
    <div className="py-2">
      <h2 className="text-lg font-semibold text-neutral-50">
        Running {scenario ? prettyName(scenario.name) : "scenario"}…
      </h2>
      <p className="mt-1 text-sm text-neutral-400">
        The agent reasons in multiple steps and may take ~10–40s. You&apos;ll be
        taken to the incident as soon as it&apos;s diagnosed.
      </p>

      <ol className="mt-5 space-y-3">
        {steps.map((step) => (
          <li key={step.key} className="flex items-center gap-3">
            <span
              className={classNames(
                "grid h-6 w-6 shrink-0 place-items-center rounded-full border text-[11px]",
                step.done
                  ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                  : step.active
                    ? "border-sky-500/40 bg-sky-500/10 text-sky-300"
                    : "border-white/10 text-neutral-500",
              )}
            >
              {step.done ? (
                <svg
                  viewBox="0 0 24 24"
                  className="h-3.5 w-3.5"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <path d="M20 6L9 17l-5-5" />
                </svg>
              ) : step.active ? (
                <Spinner />
              ) : (
                <span className="h-1.5 w-1.5 rounded-full bg-current" />
              )}
            </span>
            <span
              className={classNames(
                "text-sm",
                step.done || step.active
                  ? "text-neutral-200"
                  : "text-neutral-500",
              )}
            >
              {step.label}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Spinner() {
  return (
    <svg
      className="h-3.5 w-3.5 animate-spin"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
    >
      <circle
        className="opacity-20"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-90"
        d="M12 2a10 10 0 0 1 10 10"
        stroke="currentColor"
        strokeWidth="4"
        strokeLinecap="round"
      />
    </svg>
  );
}

function ScenarioIcon({ name }: { name: string }) {
  if (name === "database_failure") {
    return (
      <svg
        viewBox="0 0 24 24"
        className="h-4 w-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
      >
        <ellipse cx="12" cy="5" rx="8" ry="3" />
        <path d="M4 5v6c0 1.66 3.58 3 8 3s8-1.34 8-3V5" />
        <path d="M4 11v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6" />
      </svg>
    );
  }
  if (name === "memory_leak") {
    return (
      <svg
        viewBox="0 0 24 24"
        className="h-4 w-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
      >
        <rect x="4" y="4" width="16" height="16" rx="2" />
        <path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2" />
      </svg>
    );
  }
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M3 12h4l3 8 4-16 3 8h4" />
    </svg>
  );
}
