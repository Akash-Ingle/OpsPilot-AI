import type { LogReference } from "@/lib/types";

interface Props {
  refs: LogReference[];
}

/**
 * Renders the log citations the LLM provided as evidence for its diagnosis.
 * Each reference may carry a `log_id`, a prompt-relative `line_index`, a raw
 * `excerpt`, or some combination — we render whichever the model supplied.
 */
export function RelevantLogRefs({ refs }: Props) {
  if (!refs || refs.length === 0) {
    return (
      <p className="text-sm italic text-neutral-500">
        The model did not cite any specific log lines.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {refs.map((ref, idx) => (
        <li
          key={idx}
          className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3"
        >
          <div className="mb-1 flex flex-wrap items-center gap-2 text-[11px] font-medium">
            {ref.log_id != null && (
              <span className="rounded border border-sky-500/30 bg-sky-500/10 px-1.5 py-0.5 font-mono text-sky-300">
                log_id={ref.log_id}
              </span>
            )}
            {ref.line_index != null && (
              <span className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-neutral-300">
                line {ref.line_index}
              </span>
            )}
            {ref.reason && (
              <span className="text-[11px] uppercase tracking-wider text-neutral-500">
                Why
              </span>
            )}
            {ref.reason && (
              <span className="text-sm font-normal normal-case tracking-normal text-neutral-300">
                {ref.reason}
              </span>
            )}
          </div>
          {ref.excerpt && (
            <pre className="mt-1 whitespace-pre-wrap break-words rounded bg-black/30 p-2 font-mono text-[12px] leading-relaxed text-neutral-300">
              {ref.excerpt}
            </pre>
          )}
        </li>
      ))}
    </ul>
  );
}
