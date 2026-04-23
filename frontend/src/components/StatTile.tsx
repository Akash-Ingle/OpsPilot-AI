import { classNames } from "@/lib/format";
import type { ReactNode } from "react";

interface Props {
  label: string;
  value: ReactNode;
  accent?: "neutral" | "red" | "amber" | "emerald" | "sky";
  icon?: ReactNode;
}

const ACCENT: Record<NonNullable<Props["accent"]>, string> = {
  neutral: "text-neutral-200",
  red: "text-red-300",
  amber: "text-amber-300",
  emerald: "text-emerald-300",
  sky: "text-sky-300",
};

const DOT: Record<NonNullable<Props["accent"]>, string> = {
  neutral: "bg-neutral-500",
  red: "bg-red-500",
  amber: "bg-amber-400",
  emerald: "bg-emerald-500",
  sky: "bg-sky-400",
};

export function StatTile({ label, value, accent = "neutral", icon }: Props) {
  return (
    <div className="card px-4 py-3.5">
      <div className="flex items-center justify-between text-[11px] font-medium uppercase tracking-[0.14em] text-neutral-500">
        <span className="inline-flex items-center gap-1.5">
          <span className={classNames("h-1.5 w-1.5 rounded-full", DOT[accent])} />
          {label}
        </span>
        {icon && <span className="text-neutral-600">{icon}</span>}
      </div>
      <div
        className={classNames(
          "mt-2 text-2xl font-semibold tabular-nums",
          ACCENT[accent],
        )}
      >
        {value}
      </div>
    </div>
  );
}
