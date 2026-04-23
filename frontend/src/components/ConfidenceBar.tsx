import { classNames, formatConfidence } from "@/lib/format";

interface Props {
  value: number; // 0..1
  threshold?: number; // show a marker (default 0.6)
  className?: string;
  showLabel?: boolean;
}

/** A horizontal bar that color-codes confidence relative to the threshold. */
export function ConfidenceBar({
  value,
  threshold = 0.6,
  className,
  showLabel = true,
}: Props) {
  const clamped = Math.max(0, Math.min(1, value));
  const pct = clamped * 100;
  const lowConf = clamped < threshold;

  const barColor = lowConf
    ? "bg-amber-400"
    : clamped >= 0.85
      ? "bg-emerald-400"
      : "bg-sky-400";

  return (
    <div className={classNames("w-full", className)}>
      {showLabel && (
        <div className="mb-1.5 flex items-center justify-between text-[11px] text-neutral-400">
          <span className="uppercase tracking-wider">Confidence</span>
          <span
            className={classNames(
              "font-medium tabular-nums",
              lowConf ? "text-amber-300" : "text-neutral-200",
            )}
          >
            {formatConfidence(clamped)}
          </span>
        </div>
      )}
      <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
        <div
          className={classNames("h-full rounded-full transition-all", barColor)}
          style={{ width: `${pct}%` }}
        />
        {/* threshold marker */}
        <div
          className="absolute inset-y-0 w-px bg-white/25"
          style={{ left: `${threshold * 100}%` }}
          aria-hidden
        />
      </div>
    </div>
  );
}
