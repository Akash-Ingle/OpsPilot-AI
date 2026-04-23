import Link from "next/link";
import { notFound } from "next/navigation";

import { ConfidenceBar } from "@/components/ConfidenceBar";
import { EmptyState } from "@/components/EmptyState";
import { LogTable } from "@/components/LogTable";
import { ObservabilityPanel } from "@/components/ObservabilityPanel";
import { ReasoningSteps } from "@/components/ReasoningSteps";
import { RelevantLogRefs } from "@/components/RelevantLogRefs";
import { Section } from "@/components/Section";
import { SeverityBadge } from "@/components/SeverityBadge";
import { StatusBadge } from "@/components/StatusBadge";
import { ToolTimeline } from "@/components/ToolTimeline";
import { ApiError, getIncident, listLogs } from "@/lib/api";
import {
  formatAbsolute,
  formatConfidence,
  formatRelative,
} from "@/lib/format";
import type { AnalysisOut } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function IncidentDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const id = Number(params.id);
  if (!Number.isFinite(id) || id <= 0) notFound();

  let incident;
  try {
    incident = await getIncident(id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    return <FetchError err={err} />;
  }

  // Pick the latest analysis as the "authoritative" one for the UI.
  const latest = pickLatestAnalysis(incident.analyses);
  const structured = latest?.structured_output ?? null;

  // Fetch recent logs so we can show the full context, highlighting any
  // lines the model cited. We don't have an incident-scoped log endpoint yet,
  // so we pull a wide window and rely on highlighting for focus.
  let recentLogs: Awaited<ReturnType<typeof listLogs>> = [];
  try {
    recentLogs = await listLogs({ limit: 80 });
  } catch {
    recentLogs = [];
  }

  const citedLogIds = new Set<number>();
  structured?.relevant_log_lines?.forEach((ref) => {
    if (ref.log_id != null) citedLogIds.add(ref.log_id);
  });

  return (
    <>
      <BackLink />

      {/* Header */}
      <section className="mb-6">
        <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-500">
          <SeverityBadge severity={incident.severity} size="md" />
          <StatusBadge status={incident.status} />
          <span className="font-mono">
            #{incident.id.toString().padStart(4, "0")}
          </span>
        </div>
        <h1 className="mt-3 text-2xl font-semibold leading-tight tracking-tight text-neutral-50 sm:text-[28px]">
          {incident.title}
        </h1>
        <dl className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-neutral-500">
          <div>
            <dt className="inline text-neutral-500">Detected </dt>
            <dd
              className="inline text-neutral-300"
              title={formatAbsolute(incident.detected_at)}
            >
              {formatRelative(incident.detected_at)}
            </dd>
          </div>
          <div>
            <dt className="inline text-neutral-500">Updated </dt>
            <dd
              className="inline text-neutral-300"
              title={formatAbsolute(incident.updated_at)}
            >
              {formatRelative(incident.updated_at)}
            </dd>
          </div>
          {latest && (
            <div>
              <dt className="inline text-neutral-500">Analysis </dt>
              <dd className="inline text-neutral-300">
                #{latest.id} · step {latest.step_index + 1}
              </dd>
            </div>
          )}
        </dl>
      </section>

      {/* Main grid */}
      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <DiagnosisSection analysis={latest} />

          <Section
            title="Reasoning steps"
            description="Ordered chain of thought the agent used to reach its diagnosis."
            icon={<IconBrain />}
          >
            <ReasoningSteps steps={structured?.reasoning_steps ?? []} />
          </Section>

          <Section
            title="Cited evidence"
            description="Specific log lines the model flagged as supporting its conclusion."
            icon={<IconQuote />}
          >
            <RelevantLogRefs refs={structured?.relevant_log_lines ?? []} />
          </Section>

          <Section
            title="Recent logs"
            description={
              citedLogIds.size
                ? `${citedLogIds.size} line${citedLogIds.size === 1 ? "" : "s"} cited as evidence · highlighted below.`
                : "Latest log entries for context."
            }
            icon={<IconTerminal />}
            action={
              <span className="text-xs text-neutral-500 tabular-nums">
                {recentLogs.length} recent
              </span>
            }
          >
            <LogTable
              logs={recentLogs}
              highlightedIds={citedLogIds}
              emptyMessage="No recent logs ingested yet. Upload logs via POST /logs/upload."
            />
          </Section>
        </div>

        <aside className="space-y-5 lg:col-span-1">
          <Section
            title="Agent telemetry"
            description="End-to-end observability for this analysis run."
            icon={<IconGauge />}
          >
            {latest?.observability ? (
              <ObservabilityPanel obs={latest.observability} />
            ) : (
              <p className="text-sm italic text-neutral-500">
                No observability data was recorded for this analysis.
              </p>
            )}
          </Section>

          <Section
            title="Tool usage"
            description="Timeline of iterations and tool calls."
            icon={<IconWrench />}
          >
            <ToolTimeline
              iterations={latest?.observability?.iteration_trace ?? []}
            />
          </Section>
        </aside>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Subsections
// ---------------------------------------------------------------------------

function DiagnosisSection({ analysis }: { analysis: AnalysisOut | null }) {
  if (!analysis) {
    return (
      <Section title="Diagnosis" icon={<IconSparkle />}>
        <EmptyState
          title="No analysis yet"
          description="Trigger POST /analyze against this incident to generate an AI diagnosis."
        />
      </Section>
    );
  }

  const structured = analysis.structured_output;
  const confidence =
    analysis.confidence_score ?? structured?.confidence ?? null;

  return (
    <Section
      title="Diagnosis"
      description="AI-generated root cause analysis and recommended fix."
      icon={<IconSparkle />}
      action={
        confidence != null && (
          <span className="rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-xs text-neutral-300 tabular-nums">
            {formatConfidence(confidence)} confidence
          </span>
        )
      }
    >
      <div className="space-y-4">
        {structured?.issue && (
          <Field label="Issue" value={structured.issue} tone="neutral" />
        )}
        <Field
          label="Root cause"
          value={structured?.root_cause ?? "—"}
          tone="warning"
        />
        <Field
          label="Suggested fix"
          value={structured?.fix ?? "—"}
          tone="success"
        />

        {confidence != null && (
          <div className="pt-1">
            <ConfidenceBar value={confidence} />
          </div>
        )}
      </div>
    </Section>
  );
}

function Field({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "neutral" | "warning" | "success";
}) {
  const accent =
    tone === "warning"
      ? "before:bg-amber-400/60"
      : tone === "success"
        ? "before:bg-emerald-400/70"
        : "before:bg-sky-400/70";
  return (
    <div
      className={`relative rounded-lg bg-white/[0.02] py-2.5 pl-4 pr-3 before:absolute before:inset-y-2 before:left-1.5 before:w-[3px] before:rounded-full ${accent}`}
    >
      <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-neutral-500">
        {label}
      </div>
      <p className="mt-1 text-sm leading-relaxed text-neutral-100">{value}</p>
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/"
      className="mb-4 inline-flex items-center gap-1.5 text-xs font-medium text-neutral-400 transition-colors hover:text-neutral-100"
    >
      <svg
        viewBox="0 0 24 24"
        className="h-3.5 w-3.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
      >
        <path d="M15 18l-6-6 6-6" />
      </svg>
      Back to incidents
    </Link>
  );
}

function FetchError({ err }: { err: unknown }) {
  const message =
    err instanceof ApiError
      ? `${err.message}${err.status ? ` (HTTP ${err.status})` : ""}`
      : (err as Error).message;

  return (
    <div className="card border-red-500/30 bg-red-500/[0.04] p-6">
      <BackLink />
      <h1 className="text-lg font-semibold text-red-300">
        Failed to load incident
      </h1>
      <p className="mt-1.5 text-sm text-red-200/80">{message}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pickLatestAnalysis(analyses: AnalysisOut[]): AnalysisOut | null {
  if (!analyses || analyses.length === 0) return null;
  return [...analyses].sort((a, b) => {
    if (b.step_index !== a.step_index) return b.step_index - a.step_index;
    return +new Date(b.created_at) - +new Date(a.created_at);
  })[0];
}

// ---------------------------------------------------------------------------
// Inline icons (keep zero extra deps)
// ---------------------------------------------------------------------------

function IconSparkle() {
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
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8" />
    </svg>
  );
}

function IconBrain() {
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
      <path d="M9.5 2A2.5 2.5 0 007 4.5V5a2.5 2.5 0 00-2 4 3 3 0 000 5 2.5 2.5 0 002 4v.5A2.5 2.5 0 009.5 21h.5V2h-.5z" />
      <path d="M14.5 2A2.5 2.5 0 0117 4.5V5a2.5 2.5 0 012 4 3 3 0 010 5 2.5 2.5 0 01-2 4v.5a2.5 2.5 0 01-2.5 2.5H14V2h.5z" />
    </svg>
  );
}

function IconQuote() {
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
      <path d="M6 9H4a2 2 0 00-2 2v4a2 2 0 002 2h2a2 2 0 002-2v-4" />
      <path d="M18 9h-2a2 2 0 00-2 2v4a2 2 0 002 2h2a2 2 0 002-2v-4" />
    </svg>
  );
}

function IconTerminal() {
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
      <path d="M4 17l6-6-6-6" />
      <path d="M12 19h8" />
    </svg>
  );
}

function IconGauge() {
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
      <path d="M12 14l4-4" />
      <path d="M3.34 19a10 10 0 1117.32 0" />
    </svg>
  );
}

function IconWrench() {
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
      <path d="M14.7 6.3a4 4 0 00-5.6 5.6L3 18l3 3 6.1-6.1a4 4 0 005.6-5.6l-3 3-2.8-2.8 3-3z" />
    </svg>
  );
}
