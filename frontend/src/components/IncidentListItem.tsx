import Link from "next/link";

import { SeverityBadge } from "./SeverityBadge";
import { StatusBadge } from "./StatusBadge";
import { formatAbsolute, formatRelative, truncate } from "@/lib/format";
import type { IncidentOut } from "@/lib/types";

interface Props {
  incident: IncidentOut;
}

export function IncidentListItem({ incident }: Props) {
  return (
    <Link
      href={`/incidents/${incident.id}`}
      className="card card-hover group block"
    >
      <div className="flex items-start gap-4 p-4 sm:p-5">
        <div className="flex shrink-0 flex-col items-start gap-1.5 pt-0.5">
          <SeverityBadge severity={incident.severity} />
          <StatusBadge status={incident.status} />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <h3 className="truncate text-sm font-semibold text-neutral-100 group-hover:text-white">
              {incident.title}
            </h3>
            <time
              title={formatAbsolute(incident.detected_at)}
              className="shrink-0 text-xs tabular-nums text-neutral-500"
            >
              {formatRelative(incident.detected_at)}
            </time>
          </div>

          {incident.root_cause ? (
            <p className="mt-1.5 line-clamp-2 text-sm text-neutral-400">
              <span className="text-neutral-500">Root cause · </span>
              {truncate(incident.root_cause, 220)}
            </p>
          ) : (
            <p className="mt-1.5 text-sm italic text-neutral-500">
              Awaiting analysis
            </p>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-neutral-500">
            <span className="font-mono text-neutral-500">
              #{incident.id.toString().padStart(4, "0")}
            </span>
            {incident.suggested_fix && (
              <span className="inline-flex items-center gap-1.5 text-neutral-400">
                <svg
                  viewBox="0 0 24 24"
                  className="h-3.5 w-3.5 text-emerald-400"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <path d="M14.7 6.3a4 4 0 00-5.6 5.6L3 18l3 3 6.1-6.1a4 4 0 005.6-5.6l-3 3-2.8-2.8 3-3z" />
                </svg>
                Fix proposed
              </span>
            )}
          </div>
        </div>

        <svg
          viewBox="0 0 24 24"
          className="mt-1 h-4 w-4 shrink-0 text-neutral-600 transition-transform group-hover:translate-x-0.5 group-hover:text-neutral-300"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M9 18l6-6-6-6" />
        </svg>
      </div>
    </Link>
  );
}
