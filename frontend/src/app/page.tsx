import { cookies } from "next/headers";
import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { FilterBar } from "@/components/FilterBar";
import { IncidentListItem } from "@/components/IncidentListItem";
import { PageHeader } from "@/components/PageHeader";
import { SimulateButton } from "@/components/SimulateButton";
import { StatTile } from "@/components/StatTile";
import { ApiError, getProject, KEY_COOKIE, listIncidents } from "@/lib/api";
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

  // The per-browser API key is mirrored into a cookie by the Connect page. With
  // a key we show this tenant's private incidents; without one, the public
  // sandbox (the anonymous Simulate demo).
  const apiKey = cookies().get(KEY_COOKIE)?.value ?? null;

  let incidents: IncidentOut[] = [];
  let statSource: IncidentOut[] = [];
  let fetchError: string | null = null;
  let projectName: string | null = null;

  if (apiKey) {
    try {
      projectName = (await getProject(apiKey)).name;
    } catch {
      // Stale/invalid key: fall back to treating the visitor as anonymous.
    }
  }

  try {
    // Always fetch an unfiltered list for the stat tiles so counts stay
    // meaningful even when the user has filters applied. When no filter is
    // active we can reuse the same result for the list view.
    const hasFilter = Boolean(status || severity);
    const [filtered, all] = await Promise.all([
      listIncidents({ status, severity, limit: 100 }, apiKey),
      hasFilter ? listIncidents({ limit: 200 }, apiKey) : Promise.resolve(null),
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

  const isKeyed = Boolean(apiKey);

  return (
    <>
      <PageHeader
        eyebrow={isKeyed ? "Your project" : "Public demo"}
        title="Incidents"
        description={
          isKeyed
            ? "Private incidents detected from logs your app sent to OpsPilot. Click any incident to inspect the agent's reasoning, tool usage, and cited evidence."
            : "AI-analyzed incidents in the shared public sandbox. Click any incident to inspect the agent's reasoning, tool usage, and cited evidence."
        }
        actions={isKeyed ? undefined : <SimulateButton />}
      />

      <ViewBanner isKeyed={isKeyed} projectName={projectName} />

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
              : isKeyed
                ? "No incidents for your project yet. Send logs from your app to /ingest and OpsPilot will open one automatically when it detects an anomaly."
                : "Click “Simulate incident” above to generate realistic logs and watch the AI agent diagnose your first incident."
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

function ViewBanner({
  isKeyed,
  projectName,
}: {
  isKeyed: boolean;
  projectName: string | null;
}) {
  if (isKeyed) {
    return (
      <div className="mb-6 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/[0.04] px-4 py-3 text-sm">
        <span className="text-emerald-200/90">
          Viewing the private incidents for
          {projectName ? ` “${projectName}”` : " your project"}. Only someone
          with this project&apos;s API key can see them.
        </span>
        <Link
          href="/connect"
          className="font-medium text-emerald-300 hover:text-emerald-200"
        >
          Manage connection →
        </Link>
      </div>
    );
  }
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-sky-500/20 bg-sky-500/[0.04] px-4 py-3 text-sm">
      <span className="text-sky-100/80">
        This is the <strong className="font-semibold">shared public demo</strong>{" "}
        — incidents here are visible to everyone. Don&apos;t paste real or secret
        logs. Connect your app to get a private space.
      </span>
      <Link
        href="/connect"
        className="font-medium text-sky-300 hover:text-sky-200"
      >
        Connect your app →
      </Link>
    </div>
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
        The demo backend runs on a free tier that sleeps after inactivity and can
        take ~30–60s to wake up. Give it a moment and refresh — it should load on
        the next try.
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
