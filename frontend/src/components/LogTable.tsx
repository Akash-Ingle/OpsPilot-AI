import { classNames, formatAbsolute, formatRelative } from "@/lib/format";
import type { LogOut } from "@/lib/types";

interface Props {
  logs: LogOut[];
  /** Log ids the LLM cited as evidence — rendered with a highlight. */
  highlightedIds?: Set<number>;
  emptyMessage?: string;
}

const SEVERITY_STYLE: Record<string, string> = {
  debug: "text-neutral-500",
  info: "text-sky-300",
  warn: "text-amber-300",
  warning: "text-amber-300",
  error: "text-red-300",
  critical: "text-red-400",
  fatal: "text-red-400",
};

export function LogTable({
  logs,
  highlightedIds,
  emptyMessage = "No logs available.",
}: Props) {
  if (!logs || logs.length === 0) {
    return (
      <p className="text-sm italic text-neutral-500">{emptyMessage}</p>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-white/[0.06]">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-white/[0.06] bg-white/[0.02] text-left text-[11px] uppercase tracking-wider text-neutral-500">
            <th className="px-3 py-2 font-medium">Time</th>
            <th className="px-3 py-2 font-medium">Service</th>
            <th className="px-3 py-2 font-medium">Severity</th>
            <th className="px-3 py-2 font-medium">Message</th>
          </tr>
        </thead>
        <tbody className="font-mono text-[12px]">
          {logs.map((log) => {
            const highlighted = highlightedIds?.has(log.id);
            const sev = (log.severity || "").toLowerCase();
            return (
              <tr
                key={log.id}
                className={classNames(
                  "border-b border-white/[0.04] last:border-b-0 transition-colors",
                  highlighted
                    ? "bg-sky-500/[0.06] hover:bg-sky-500/[0.09]"
                    : "hover:bg-white/[0.02]",
                )}
              >
                <td className="whitespace-nowrap px-3 py-1.5 align-top text-neutral-400">
                  <time title={formatAbsolute(log.timestamp)}>
                    {formatRelative(log.timestamp)}
                  </time>
                </td>
                <td className="whitespace-nowrap px-3 py-1.5 align-top text-neutral-300">
                  {log.service_name}
                </td>
                <td className="whitespace-nowrap px-3 py-1.5 align-top">
                  <span
                    className={classNames(
                      "uppercase",
                      SEVERITY_STYLE[sev] ?? "text-neutral-300",
                    )}
                  >
                    {log.severity}
                  </span>
                </td>
                <td className="px-3 py-1.5 align-top text-neutral-200">
                  <div className="flex items-start gap-2">
                    {highlighted && (
                      <span
                        title="Cited by the AI as evidence"
                        className="mt-0.5 inline-flex shrink-0 items-center rounded border border-sky-500/40 bg-sky-500/10 px-1 py-[1px] text-[10px] font-sans font-semibold text-sky-300"
                      >
                        cited
                      </span>
                    )}
                    <span className="break-words">{log.message}</span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
