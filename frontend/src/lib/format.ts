/** Display helpers: dates, severity ordering, number formatting. */

import type { Severity } from "./types";

const RELATIVE_UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ["year", 60 * 60 * 24 * 365],
  ["month", 60 * 60 * 24 * 30],
  ["week", 60 * 60 * 24 * 7],
  ["day", 60 * 60 * 24],
  ["hour", 60 * 60],
  ["minute", 60],
  ["second", 1],
];

/** "3 minutes ago", "in 2 hours", etc. Falls back to the raw ISO string. */
export function formatRelative(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return iso;

  const diffSec = Math.round((then.getTime() - now.getTime()) / 1000);
  const abs = Math.abs(diffSec);
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

  for (const [unit, secondsPerUnit] of RELATIVE_UNITS) {
    if (abs >= secondsPerUnit || unit === "second") {
      const value = Math.round(diffSec / secondsPerUnit);
      return rtf.format(value, unit);
    }
  }
  return rtf.format(diffSec, "second");
}

/** "Apr 23, 2026, 14:05:12 UTC" style absolute timestamp. */
export function formatAbsolute(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1) return "<1 ms";
  if (ms < 1000) return `${ms.toFixed(ms < 10 ? 1 : 0)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 2 : 1)} s`;
  const m = Math.floor(s / 60);
  const rem = (s - m * 60).toFixed(0);
  return `${m}m ${rem}s`;
}

export function formatConfidence(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

/** Sort key so "critical" > "high" > "medium" > "low". */
const SEVERITY_RANK: Record<Severity, number> = {
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
};

export function severityRank(s: Severity): number {
  return SEVERITY_RANK[s] ?? 0;
}

export function truncate(text: string | null | undefined, max: number): string {
  if (!text) return "";
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1).trimEnd()}…`;
}

export function classNames(
  ...values: Array<string | false | null | undefined>
): string {
  return values.filter(Boolean).join(" ");
}
