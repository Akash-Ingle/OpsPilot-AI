import { classNames, formatDuration } from "@/lib/format";
import type { AgentObservability, StoppedReason } from "@/lib/types";

interface Props {
  obs: AgentObservability;
}

const STOP_STYLE: Record<StoppedReason, string> = {
  confident: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  max_iterations: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  no_progress: "bg-red-500/10 text-red-300 ring-red-500/30",
  low_confidence_final: "bg-red-500/10 text-red-300 ring-red-500/30",
};

const STOP_LABEL: Record<StoppedReason, string> = {
  confident: "Confident",
  max_iterations: "Hit iteration cap",
  no_progress: "No progress",
  low_confidence_final: "Low confidence at cap",
};

export function ObservabilityPanel({ obs }: Props) {
  const tools = obs.tools_called;
  return (
    <div className="space-y-4">
      <StoppedReasonPill reason={obs.stopped_reason} />

      <div className="grid grid-cols-2 gap-3">
        <Metric
          label="Iterations"
          value={`${obs.iterations} / ${obs.max_iterations}`}
        />
        <Metric label="Duration" value={formatDuration(obs.duration_ms)} />
        <Metric label="Tools called" value={tools.length} />
        <Metric
          label="Low-conf retries"
          value={obs.low_confidence_retries}
          accent={obs.low_confidence_retries > 0 ? "amber" : undefined}
        />
      </div>

      <ConfidenceSparkline values={obs.confidence_progression} />
    </div>
  );
}

function StoppedReasonPill({ reason }: { reason: StoppedReason }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2.5">
      <span className="text-[11px] uppercase tracking-wider text-neutral-500">
        Stopped
      </span>
      <span
        className={classNames(
          "rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset",
          STOP_STYLE[reason],
        )}
      >
        {STOP_LABEL[reason]}
      </span>
    </div>
  );
}

function Metric({
  label,
  value,
  accent,
}: {
  label: string;
  value: React.ReactNode;
  accent?: "amber";
}) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2.5">
      <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-neutral-500">
        {label}
      </div>
      <div
        className={classNames(
          "mt-1 text-lg font-semibold tabular-nums",
          accent === "amber" ? "text-amber-300" : "text-neutral-100",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function ConfidenceSparkline({ values }: { values: number[] }) {
  if (!values || values.length === 0) return null;

  const width = 240;
  const height = 48;
  const pad = 4;
  const usable = width - pad * 2;

  const xStep = values.length > 1 ? usable / (values.length - 1) : 0;
  const points = values
    .map((v, i) => {
      const x = pad + i * xStep;
      const clamped = Math.max(0, Math.min(1, v));
      const y = pad + (1 - clamped) * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const first = values[0];
  const last = values[values.length - 1];
  const delta = last - first;

  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-medium uppercase tracking-[0.14em] text-neutral-500">
          Confidence progression
        </span>
        <span
          className={classNames(
            "text-xs tabular-nums",
            delta >= 0 ? "text-emerald-300" : "text-red-300",
          )}
        >
          {delta >= 0 ? "+" : ""}
          {(delta * 100).toFixed(0)}%
        </span>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className="mt-2 h-12 w-full"
        aria-label="Confidence progression sparkline"
      >
        {/* 60% threshold baseline */}
        <line
          x1={pad}
          x2={width - pad}
          y1={pad + 0.4 * (height - pad * 2)}
          y2={pad + 0.4 * (height - pad * 2)}
          stroke="rgba(255,255,255,0.12)"
          strokeDasharray="2 3"
        />
        <polyline
          fill="none"
          stroke="rgb(56 189 248)"
          strokeWidth={1.75}
          strokeLinejoin="round"
          strokeLinecap="round"
          points={points}
        />
        {values.map((v, i) => {
          const x = pad + i * xStep;
          const clamped = Math.max(0, Math.min(1, v));
          const y = pad + (1 - clamped) * (height - pad * 2);
          return (
            <circle
              key={i}
              cx={x}
              cy={y}
              r={2.5}
              fill="rgb(56 189 248)"
              stroke="#0b0c0f"
              strokeWidth={1}
            />
          );
        })}
      </svg>
      <div className="mt-1 flex justify-between text-[10px] tabular-nums text-neutral-500">
        <span>start {(first * 100).toFixed(0)}%</span>
        <span>end {(last * 100).toFixed(0)}%</span>
      </div>
    </div>
  );
}
