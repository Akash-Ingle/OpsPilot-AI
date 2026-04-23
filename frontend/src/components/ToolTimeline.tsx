import { classNames, formatDuration } from "@/lib/format";
import type { IterationRecord } from "@/lib/types";

interface Props {
  iterations: IterationRecord[];
}

/**
 * A vertical timeline of the agent's iterations. Each iteration shows:
 *   - step index + confidence
 *   - whether it was a low-confidence forced retry
 *   - the requested action and any tool dispatched (with outcome + duration)
 */
export function ToolTimeline({ iterations }: Props) {
  if (!iterations || iterations.length === 0) {
    return (
      <p className="text-sm italic text-neutral-500">
        No iteration telemetry recorded for this run.
      </p>
    );
  }

  return (
    <ol className="relative">
      {iterations.map((it, idx) => {
        const tool = it.tool_call;
        const ok = tool ? tool.ok : true;
        const isLast = idx === iterations.length - 1;
        return (
          <li key={it.step} className="relative flex gap-3 pb-5 last:pb-0">
            {!isLast && (
              <span
                className="absolute left-[11px] top-6 h-[calc(100%-0.25rem)] w-px bg-white/10"
                aria-hidden
              />
            )}

            <div className="z-10 mt-0.5 flex flex-col items-center">
              <span
                className={classNames(
                  "grid h-6 w-6 place-items-center rounded-full border font-mono text-[11px] font-semibold",
                  tool
                    ? ok
                      ? "border-sky-500/40 bg-sky-500/10 text-sky-200"
                      : "border-red-500/40 bg-red-500/10 text-red-200"
                    : "border-white/10 bg-white/[0.04] text-neutral-300",
                )}
              >
                {it.step}
              </span>
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-neutral-100">
                  {tool ? (
                    <>
                      <span className="font-mono text-sky-300">{tool.name}</span>
                      <span className="text-neutral-500">()</span>
                    </>
                  ) : it.needs_more_data ? (
                    <span className="text-neutral-300">
                      requested{" "}
                      <span className="font-mono text-neutral-400">
                        {it.requested_action}
                      </span>
                    </span>
                  ) : (
                    <span className="text-neutral-300">Reasoning only</span>
                  )}
                </span>

                {tool && (
                  <span
                    className={classNames(
                      "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ring-1 ring-inset",
                      ok
                        ? "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30"
                        : "bg-red-500/10 text-red-300 ring-red-500/30",
                    )}
                  >
                    {ok ? "ok" : "failed"}
                  </span>
                )}

                {it.low_confidence_retry && (
                  <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300 ring-1 ring-inset ring-amber-500/30">
                    low-conf retry
                  </span>
                )}

                <span className="ml-auto shrink-0 text-[11px] tabular-nums text-neutral-500">
                  conf {(it.confidence * 100).toFixed(0)}% · {formatDuration(it.duration_ms)}
                </span>
              </div>

              {tool && Object.keys(tool.args).length > 0 && (
                <pre className="mt-1.5 overflow-x-auto rounded bg-black/30 p-2 font-mono text-[12px] leading-relaxed text-neutral-300">
                  {JSON.stringify(tool.args, null, 2)}
                </pre>
              )}

              {tool && !ok && tool.error && (
                <p className="mt-1.5 text-xs text-red-300">
                  <span className="text-neutral-500">error · </span>
                  {tool.error}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
