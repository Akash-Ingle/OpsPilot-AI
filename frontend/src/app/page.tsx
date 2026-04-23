import { EmptyState } from "@/components/EmptyState";
import { FilterBar } from "@/components/FilterBar";
import { IncidentListItem } from "@/components/IncidentListItem";
import { PageHeader } from "@/components/PageHeader";
import { StatTile } from "@/components/StatTile";
import { ApiError, listIncidents } from "@/lib/api";
import { severityRank } from "@/lib/format";
import type { IncidentOut, IncidentStatus, Severity } from "@/lib/types";

export const dynamic = "force-dynamic";

interface SearchParams {
  status?: string;
  severity?: string;
}

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const status = normaliseStatus(searchParams.status);
  const severity = normaliseSeverity(searchParams.severity);

  let incidents: IncidentOut[] = [];
  let statSource: IncidentOut[] = [];
  let fetchError: string | null = null;

  try {
    // Always fetch an unfiltered list for the stat tiles so counts stay
    // meaningful even when the user has filters applied. When no filter is
    // active we can reuse the same result for the list view.
    const hasFilter = Boolean(status || severity);
    const [filtered, all] = await Promise.all([
      listIncidents({ status, severity, limit: 100 }),
      hasFilter ? listIncidents({ limit: 200 }) : Promise.resolve(null),
    ]);

    incidents = [...filtered].sort(
      (a, b) =>
        severityRank(b.severity) - severityRank(a.severity) ||
        +new Date(b.detected_at) - +new Date(a.detected_at),
    );
    statSource = all ?? incidents;
  } catch (err) {
    fetchError =
      err instanceof ApiError
        ? `${err.message}${err.status ? ` (HTTP ${err.status})` : ""}`
        : (err as Error).message;
  }

  const counts = {
    total: statSource.length,
    open: statSource.filter((i) => i.status === "open").length,
    investigating: statSource.filter((i) => i.status === "investigating").length,
    resolved: statSource.filter((i) => i.status === "resolved").length,
    critical: statSource.filter((i) => i.severity === "critical").length,
  };

  return (
    <>
      <PageHeader
        eyebrow="Dashboard"
        title="Incidents"
        description="AI-analyzed incidents detected from your service logs. Click any incident to inspect the agent's reasoning, tool usage, and cited evidence."
      />

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
        <StatTile label="Total" value={counts.total} />
        <StatTile label="Open" value={counts.open} accent="red" />
        <StatTile label="Investigating" value={counts.investigating} accent="amber" />
        <StatTile label="Resolved" value={counts.resolved} accent="emerald" />
        <StatTile label="Critical" value={counts.critical} accent="red" />
      </div>

      <FilterBar />

      {fetchError ? (
        <FetchErrorBox message={fetchError} />
      ) : incidents.length === 0 ? (
        <EmptyState
          title={
            status || severity
              ? "No incidents match these filters"
              : "No incidents yet"
          }
          description={
            status || severity
              ? "Try clearing filters or choosing a different severity."
              : "Run POST /simulate and POST /analyze on the backend to generate your first analyzed incident."
          }
        />
      ) : (
        <div className="space-y-2.5">
          {incidents.map((incident) => (
            <IncidentListItem key={incident.id} incident={incident} />
          ))}
        </div>
      )}
    </>
  );
}

function FetchErrorBox({ message }: { message: string }) {
  return (
    <div className="card border-red-500/30 bg-red-500/[0.04] p-5">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-red-300">
        <svg
          viewBox="0 0 24 24"
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
          <path d="M12 9v4M12 17h.01" />
        </svg>
        Couldn’t load incidents
      </h3>
      <p className="mt-1.5 text-sm text-red-200/80">{message}</p>
      <p className="mt-3 text-xs text-neutral-400">
        Make sure the FastAPI backend is running and that{" "}
        <code className="kbd">NEXT_PUBLIC_API_URL</code> points at it (default{" "}
        <code className="kbd">http://localhost:8000/api/v1</code>).
      </p>
    </div>
  );
}

// --- Helpers ----------------------------------------------------------------

function normaliseStatus(v: string | undefined): IncidentStatus | undefined {
  const allowed = new Set<IncidentStatus>([
    "open",
    "investigating",
    "resolved",
    "closed",
    "dismissed",
  ]);
  return v && allowed.has(v as IncidentStatus) ? (v as IncidentStatus) : undefined;
}

function normaliseSeverity(v: string | undefined): Severity | undefined {
  const allowed = new Set<Severity>(["low", "medium", "high", "critical"]);
  return v && allowed.has(v as Severity) ? (v as Severity) : undefined;
}
