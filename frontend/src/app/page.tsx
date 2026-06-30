import Link from "next/link";

import { EmptyState } from "@/components/EmptyState";
import { FilterBar } from "@/components/FilterBar";
import { IncidentListItem } from "@/components/IncidentListItem";
import { PageHeader } from "@/components/PageHeader";
import { SimulateButton } from "@/components/SimulateButton";
import { StatTile } from "@/components/StatTile";
import { ApiError, listIncidents } from "@/lib/api";
import { currentUser, sessionCookie } from "@/lib/auth-server";
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
  // No login wall: anonymous visitors see the public sandbox; signed-in users
  // see their own private incidents. The cookie (present only when logged in)
  // is forwarded so the backend scopes the result accordingly.
  const user = await currentUser();
  const cookie = sessionCookie();
  const isLoggedIn = Boolean(user);

  const status = normaliseStatus(searchParams.status);
  const severity = normaliseSeverity(searchParams.severity);

  let incidents: IncidentOut[] = [];
  let statSource: IncidentOut[] = [];
  let fetchError: string | null = null;

  try {
    const hasFilter = Boolean(status || severity);
    const [filtered, all] = await Promise.all([
      listIncidents({ status, severity, limit: 100 }, cookie),
      hasFilter ? listIncidents({ limit: 200 }, cookie) : Promise.resolve(null),
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
        eyebrow={isLoggedIn ? "Your incidents" : "Public demo"}
        title="Incidents"
        description={
          isLoggedIn
            ? "Private incidents from your projects. Click any incident to inspect the agent's reasoning, tool usage, and cited evidence."
            : "AI-analyzed incidents in the shared public sandbox. Click any incident to inspect the agent's reasoning, tool usage, and cited evidence."
        }
        actions={<SimulateButton />}
      />

      <ViewBanner isLoggedIn={isLoggedIn} email={user?.email ?? null} />

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
            status || severity ? (
              "Try clearing filters or choosing a different severity."
            ) : isLoggedIn ? (
              <>
                No incidents for your projects yet. Click “Simulate incident”, or{" "}
                <Link href="/connect" className="text-sky-400 hover:text-sky-300">
                  connect your app
                </Link>{" "}
                to stream real logs and have OpsPilot open incidents automatically.
              </>
            ) : (
              "Click “Simulate incident” above to generate realistic logs and watch the AI agent diagnose your first incident."
            )
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
  isLoggedIn,
  email,
}: {
  isLoggedIn: boolean;
  email: string | null;
}) {
  if (isLoggedIn) {
    return (
      <div className="mb-6 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/[0.04] px-4 py-3 text-sm">
        <span className="text-emerald-200/90">
          Viewing your private incidents{email ? ` (${email})` : ""}. Only you can
          see them.
        </span>
        <Link
          href="/connect"
          className="font-medium text-emerald-300 hover:text-emerald-200"
        >
          Connect your app →
        </Link>
      </div>
    );
  }
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-sky-500/20 bg-sky-500/[0.04] px-4 py-3 text-sm">
      <span className="text-sky-100/80">
        This is the <strong className="font-semibold">shared public demo</strong>{" "}
        — incidents here are visible to everyone. Don&apos;t paste real or secret
        logs.{" "}
        <Link href="/login" className="font-medium text-sky-300 hover:text-sky-200">
          Sign up
        </Link>{" "}
        to get a private space for your app.
      </span>
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
