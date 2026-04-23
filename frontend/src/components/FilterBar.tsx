"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

import { classNames } from "@/lib/format";
import type { IncidentStatus, Severity } from "@/lib/types";

const STATUS_OPTIONS: Array<{ id: "" | IncidentStatus; label: string }> = [
  { id: "", label: "All" },
  { id: "open", label: "Open" },
  { id: "investigating", label: "Investigating" },
  { id: "resolved", label: "Resolved" },
];

const SEVERITY_OPTIONS: Array<{ id: "" | Severity; label: string }> = [
  { id: "", label: "All severities" },
  { id: "critical", label: "Critical" },
  { id: "high", label: "High" },
  { id: "medium", label: "Medium" },
  { id: "low", label: "Low" },
];

/**
 * Client-side filter controls that sync their state to the URL query string,
 * so filters are shareable and survive refreshes. The server-rendered page
 * reads the same params and re-fetches accordingly.
 */
export function FilterBar() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const status = (params.get("status") ?? "") as "" | IncidentStatus;
  const severity = (params.get("severity") ?? "") as "" | Severity;

  const buildHref = useCallback(
    (key: "status" | "severity", value: string) => {
      const next = new URLSearchParams(params.toString());
      if (value) next.set(key, value);
      else next.delete(key);
      const qs = next.toString();
      return qs ? `${pathname}?${qs}` : pathname;
    },
    [params, pathname],
  );

  const pushFilter = useCallback(
    (key: "status" | "severity", value: string) => {
      router.push(buildHref(key, value), { scroll: false });
    },
    [buildHref, router],
  );

  const hasFilters = useMemo(
    () => Boolean(status) || Boolean(severity),
    [status, severity],
  );

  return (
    <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-wrap items-center gap-1 rounded-lg border border-white/[0.06] bg-[var(--bg-elevated)] p-1">
        {STATUS_OPTIONS.map((opt) => {
          const active = status === opt.id;
          return (
            <button
              key={opt.id || "any"}
              type="button"
              onClick={() => pushFilter("status", opt.id)}
              className={classNames(
                "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                active
                  ? "bg-white/10 text-white shadow-sm"
                  : "text-neutral-400 hover:bg-white/5 hover:text-neutral-200",
              )}
            >
              {opt.label}
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <label className="relative">
          <span className="sr-only">Filter by severity</span>
          <select
            value={severity}
            onChange={(e) => pushFilter("severity", e.target.value)}
            className="appearance-none rounded-lg border border-white/[0.06] bg-[var(--bg-elevated)] py-1.5 pl-3 pr-8 text-xs font-medium text-neutral-200 outline-none transition-colors hover:border-white/[0.12] focus:border-sky-500/60 focus:ring-2 focus:ring-sky-500/20"
          >
            {SEVERITY_OPTIONS.map((opt) => (
              <option key={opt.id || "any"} value={opt.id} className="bg-neutral-900">
                {opt.label}
              </option>
            ))}
          </select>
          <svg
            viewBox="0 0 24 24"
            className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-500"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <path d="M6 9l6 6 6-6" />
          </svg>
        </label>

        {hasFilters && (
          <button
            type="button"
            onClick={() => router.push(pathname, { scroll: false })}
            className="rounded-lg border border-white/[0.06] px-3 py-1.5 text-xs font-medium text-neutral-400 transition-colors hover:border-white/[0.12] hover:text-neutral-200"
          >
            Clear
          </button>
        )}
      </div>
    </div>
  );
}
