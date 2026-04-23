import { classNames } from "@/lib/format";
import type { IncidentStatus } from "@/lib/types";

const STYLES: Record<string, string> = {
  open: "bg-red-500/10 text-red-300 ring-red-500/30",
  investigating: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  resolved: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  closed: "bg-neutral-500/10 text-neutral-300 ring-neutral-500/30",
  dismissed: "bg-neutral-500/10 text-neutral-400 ring-neutral-500/20",
};

function label(status: IncidentStatus | string): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

interface Props {
  status: IncidentStatus | string;
  className?: string;
}

export function StatusBadge({ status, className }: Props) {
  const style = STYLES[status] ?? STYLES.closed;
  return (
    <span
      className={classNames(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset",
        style,
        className,
      )}
    >
      {label(status)}
    </span>
  );
}
