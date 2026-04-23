import { classNames } from "@/lib/format";
import type { Severity } from "@/lib/types";

type Size = "sm" | "md";

const STYLES: Record<Severity, string> = {
  critical:
    "bg-red-500/10 text-red-300 ring-red-500/30",
  high:
    "bg-orange-500/10 text-orange-300 ring-orange-500/30",
  medium:
    "bg-yellow-500/10 text-yellow-200 ring-yellow-500/30",
  low: "bg-sky-500/10 text-sky-300 ring-sky-500/30",
};

const DOT: Record<Severity, string> = {
  critical: "bg-red-500",
  high: "bg-orange-500",
  medium: "bg-yellow-400",
  low: "bg-sky-400",
};

const LABEL: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

interface Props {
  severity: Severity | string;
  size?: Size;
  className?: string;
}

/** Ring + dot pill that works well both inline and in a table row. */
export function SeverityBadge({ severity, size = "sm", className }: Props) {
  const key = (severity as Severity) in STYLES ? (severity as Severity) : "low";
  return (
    <span
      className={classNames(
        "inline-flex items-center gap-1.5 rounded-full font-medium ring-1 ring-inset",
        size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs",
        STYLES[key],
        className,
      )}
    >
      <span
        className={classNames(
          "inline-block rounded-full",
          size === "sm" ? "h-1.5 w-1.5" : "h-2 w-2",
          DOT[key],
          key === "critical" && "animate-pulse-soft",
        )}
      />
      {LABEL[key]}
    </span>
  );
}
