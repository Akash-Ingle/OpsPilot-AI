"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createProject,
  deleteProject,
  ingestLogs,
  listProjects,
  PUBLIC_BACKEND_URL,
  updateProjectById,
  type IngestLogItem,
} from "@/lib/api";
import type { ProjectCreated, ProjectOut } from "@/lib/types";

const INGEST_URL = `${PUBLIC_BACKEND_URL}/ingest`;

// A canned burst that trips the anomaly detector so the demo loop is instant.
const SAMPLE_LOGS: IngestLogItem[] = [
  ...Array.from({ length: 12 }, (_, i) => ({
    service_name: "orders-svc",
    severity: "error",
    message: `connection timeout to db-primary after 5000ms pool=orders-pool waiting=${i}`,
  })),
  {
    service_name: "orders-svc",
    severity: "critical",
    message: "FATAL: connection pool exhausted (size=20 in_use=20) queue_depth=80",
  },
];

export default function ConnectPage() {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectOut[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [freshKey, setFreshKey] = useState<ProjectCreated | null>(null);

  const refresh = useCallback(async () => {
    try {
      setProjects(await listProjects());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/login?next=/connect");
        return;
      }
      // transient — keep last known state
    }
  }, [router]);

  useEffect(() => {
    listProjects()
      .then(setProjects)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login?next=/connect");
        }
      })
      .finally(() => setLoading(false));
  }, [router]);

  // Poll live stats while on the page.
  useEffect(() => {
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [refresh]);

  return (
    <div className="space-y-8">
      <header>
        <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-neutral-500">
          Connect your app
        </p>
        <h1 className="text-2xl font-semibold tracking-tight text-neutral-50 sm:text-3xl">
          Point your logs at OpsPilot
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-neutral-400">
          Stream your app&apos;s logs to OpsPilot with one HTTP call. It watches the
          stream, and the moment something looks wrong it pulls the relevant lines,
          diagnoses the root cause, opens an incident, and pings you in Slack —
          before you go digging.
        </p>
      </header>

      {freshKey && (
        <FreshKeyCard created={freshKey} onDismiss={() => setFreshKey(null)} />
      )}

      <CreateProject
        onCreated={(created) => {
          setFreshKey(created);
          refresh();
        }}
      />

      {loading ? (
        <div className="card p-6 text-sm text-neutral-400">Loading…</div>
      ) : projects && projects.length > 0 ? (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-neutral-200">
            Your projects
          </h2>
          {projects.map((p) => (
            <ProjectCard key={p.id} project={p} onSaved={refresh} />
          ))}
        </div>
      ) : (
        <p className="text-sm text-neutral-500">
          No projects yet. Create one above to get an API key.
        </p>
      )}
    </div>
  );
}

function CreateProject({
  onCreated,
}: {
  onCreated: (created: ProjectCreated) => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createProject(name.trim());
      onCreated(created);
      setName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create project");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="card max-w-xl space-y-4 p-6">
      <div>
        <h2 className="text-sm font-semibold text-neutral-100">
          Create a project
        </h2>
        <p className="mt-1 text-sm text-neutral-400">
          A project groups your logs and gets its own API key. You&apos;ll see the
          key once — copy it somewhere safe.
        </p>
      </div>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="e.g. my-store-backend"
        maxLength={120}
        className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-neutral-100 outline-none placeholder:text-neutral-600 focus:border-sky-500/50"
      />
      {error && <p className="text-sm text-red-300">{error}</p>}
      <button
        type="submit"
        disabled={busy || !name.trim()}
        className="rounded-lg bg-gradient-to-br from-sky-500 to-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-indigo-500/20 transition-opacity disabled:opacity-50"
      >
        {busy ? "Creating…" : "Create project & get API key"}
      </button>
    </form>
  );
}

function FreshKeyCard({
  created,
  onDismiss,
}: {
  created: ProjectCreated;
  onDismiss: () => void;
}) {
  return (
    <div className="card space-y-5 border-amber-500/30 bg-amber-500/[0.05] p-6">
      <div>
        <h3 className="text-sm font-semibold text-amber-200">
          Save the API key for “{created.name}” now
        </h3>
        <p className="mt-1 text-sm text-amber-100/80">
          This is the only time the full key is shown. Copy it into your app&apos;s
          secrets — it won&apos;t be displayed again.
        </p>
        <div className="mt-3 flex items-center gap-2">
          <code className="flex-1 truncate rounded-md border border-white/10 bg-black/30 px-3 py-2 font-mono text-xs text-neutral-200">
            {created.api_key}
          </code>
          <CopyButton value={created.api_key} label="Copy key" />
          <button
            onClick={onDismiss}
            className="rounded-md border border-white/10 px-3 py-2 text-xs text-neutral-300 hover:bg-white/5"
          >
            Got it
          </button>
        </div>
      </div>

      <SnippetSection apiKey={created.api_key} />
      <SampleLogs apiKey={created.api_key} />
    </div>
  );
}

function ProjectCard({
  project,
  onSaved,
}: {
  project: ProjectOut;
  onSaved: () => void;
}) {
  const waiting = project.log_count === 0;
  return (
    <div className="card p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span
            className={`h-2.5 w-2.5 rounded-full ${
              waiting ? "bg-neutral-500" : "bg-emerald-400 animate-pulse"
            }`}
          />
          <h3 className="text-sm font-semibold text-neutral-100">
            {project.name}
          </h3>
          <span className="rounded-full border border-white/10 bg-white/[0.03] px-2 py-0.5 font-mono text-[10px] text-neutral-400">
            {project.key_prefix}…
          </span>
        </div>
        <div className="flex items-center gap-4">
          {project.incident_count > 0 && (
            <Link
              href="/"
              className="text-sm font-medium text-sky-400 hover:text-sky-300"
            >
              View incidents →
            </Link>
          )}
          <DeleteProject project={project} onDeleted={onSaved} />
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Stat label="Logs ingested" value={project.log_count} />
        <Stat label="Incidents opened" value={project.incident_count} />
        <Stat
          label="Last auto-analysis"
          value={
            project.last_auto_analysis_at
              ? new Date(project.last_auto_analysis_at).toLocaleTimeString()
              : "—"
          }
        />
      </div>

      <SlackSection project={project} onSaved={onSaved} />
    </div>
  );
}

function DeleteProject({
  project,
  onDeleted,
}: {
  project: ProjectOut;
  onDeleted: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await deleteProject(project.id);
      onDeleted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete project");
      setBusy(false);
    }
  }

  if (!confirming) {
    return (
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="text-sm font-medium text-neutral-500 transition-colors hover:text-red-300"
      >
        Delete
      </button>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-neutral-400">
        {error ?? "Delete project and all its logs/incidents?"}
      </span>
      <button
        type="button"
        onClick={remove}
        disabled={busy}
        className="rounded-md border border-red-500/30 bg-red-500/10 px-2.5 py-1 text-xs font-semibold text-red-200 transition-colors hover:bg-red-500/20 disabled:opacity-50"
      >
        {busy ? "Deleting…" : "Delete"}
      </button>
      <button
        type="button"
        onClick={() => {
          setConfirming(false);
          setError(null);
        }}
        disabled={busy}
        className="rounded-md border border-white/10 px-2.5 py-1 text-xs font-medium text-neutral-300 transition-colors hover:bg-white/5 disabled:opacity-50"
      >
        Cancel
      </button>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3">
      <p className="text-[11px] uppercase tracking-wider text-neutral-500">
        {label}
      </p>
      <p className="mt-1 text-lg font-semibold text-neutral-100">{value}</p>
    </div>
  );
}

function SampleLogs({ apiKey }: { apiKey: string }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);

  async function send() {
    setBusy(true);
    setMsg(null);
    setIsError(false);
    try {
      const res = await ingestLogs(apiKey, SAMPLE_LOGS);
      setMsg(
        `Sent ${res.ingested} logs. The watcher is analyzing them — an incident should appear on your dashboard within a few seconds.`,
      );
    } catch (err) {
      setIsError(true);
      setMsg(err instanceof Error ? err.message : "Failed to send sample logs");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.02] p-4">
      <h4 className="text-sm font-semibold text-neutral-100">
        See it work right now
      </h4>
      <p className="mt-1 max-w-2xl text-sm text-neutral-400">
        Send a sample burst of database-failure logs. OpsPilot will detect the
        anomaly, diagnose it, and open an incident automatically.
      </p>
      <button
        onClick={send}
        disabled={busy}
        className="mt-3 rounded-lg border border-white/10 bg-white/[0.04] px-4 py-2 text-sm font-semibold text-neutral-100 transition-colors hover:bg-white/[0.08] disabled:opacity-50"
      >
        {busy ? "Sending…" : "Send sample logs"}
      </button>
      {msg && (
        <p className={`mt-3 text-sm ${isError ? "text-red-300" : "text-emerald-300/90"}`}>
          {msg}
        </p>
      )}
    </div>
  );
}

const TABS = ["curl", "Python", "Node.js"] as const;
type Tab = (typeof TABS)[number];

function SnippetSection({ apiKey }: { apiKey: string }) {
  const [tab, setTab] = useState<Tab>("curl");
  const snippet = buildSnippet(tab, INGEST_URL, apiKey);

  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.02] p-4">
      <h4 className="text-sm font-semibold text-neutral-100">
        Wire it into your app
      </h4>
      <p className="mt-1 text-sm text-neutral-400">
        Ship logs to <code className="text-neutral-300">{INGEST_URL}</code> with
        your key in the <code className="text-neutral-300">Authorization</code>{" "}
        header. Batches of up to 1,000 lines per call.
      </p>

      <div className="mt-4 flex gap-1">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              tab === t
                ? "bg-white/10 text-neutral-100"
                : "text-neutral-400 hover:bg-white/5"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="relative mt-3">
        <pre className="overflow-x-auto rounded-lg border border-white/10 bg-black/40 p-4 text-xs leading-relaxed text-neutral-200">
          <code>{snippet}</code>
        </pre>
        <div className="absolute right-3 top-3">
          <CopyButton value={snippet} label="Copy" />
        </div>
      </div>
    </div>
  );
}

function SlackSection({
  project,
  onSaved,
}: {
  project: ProjectOut;
  onSaved: () => void;
}) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);

  async function save() {
    setBusy(true);
    setMsg(null);
    setIsError(false);
    try {
      await updateProjectById(project.id, { slack_webhook_url: url.trim() });
      setMsg("Saved. New incidents will be posted to your Slack channel.");
      setUrl("");
      onSaved();
    } catch (err) {
      setIsError(true);
      setMsg(err instanceof Error ? err.message : "Failed to save webhook");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-5 rounded-lg border border-white/10 bg-white/[0.02] p-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-neutral-100">
          Get alerts in Slack
        </h4>
        {project.slack_configured && (
          <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-medium text-emerald-300">
            Connected
          </span>
        )}
      </div>
      <p className="mt-1 max-w-2xl text-sm text-neutral-400">
        Paste a Slack{" "}
        <a
          href="https://api.slack.com/messaging/webhooks"
          target="_blank"
          rel="noreferrer"
          className="text-sky-400 hover:text-sky-300"
        >
          incoming webhook URL
        </a>
        . OpsPilot posts the severity, root cause, fix, and a link when it opens an
        incident.
      </p>
      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://hooks.slack.com/services/T…/B…/…"
          className="flex-1 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-neutral-100 outline-none placeholder:text-neutral-600 focus:border-sky-500/50"
        />
        <button
          onClick={save}
          disabled={busy || !url.trim()}
          className="rounded-lg bg-gradient-to-br from-sky-500 to-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-indigo-500/20 disabled:opacity-50"
        >
          {busy ? "Saving…" : "Save webhook"}
        </button>
      </div>
      {msg && (
        <p className={`mt-3 text-sm ${isError ? "text-red-300" : "text-emerald-300/90"}`}>
          {msg}
        </p>
      )}
    </div>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function copy() {
    navigator.clipboard?.writeText(value).then(() => {
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <button
      onClick={copy}
      className="rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-medium text-neutral-200 hover:bg-white/[0.08]"
    >
      {copied ? "Copied!" : label}
    </button>
  );
}

function buildSnippet(tab: Tab, ingestUrl: string, key: string): string {
  if (tab === "curl") {
    return `curl -X POST ${ingestUrl} \\
  -H "Authorization: Bearer ${key}" \\
  -H "Content-Type: application/json" \\
  -d '{"logs":[{"service_name":"web","severity":"error","message":"OutOfMemoryError: Java heap space"}]}'`;
  }
  if (tab === "Python") {
    return `import logging, requests

OPSPILOT_URL = "${ingestUrl}"
OPSPILOT_KEY = "${key}"

class OpsPilotHandler(logging.Handler):
    """Ship WARNING+ logs to OpsPilot. Never lets logging break the app."""
    def emit(self, record):
        try:
            requests.post(
                OPSPILOT_URL,
                headers={"Authorization": f"Bearer {OPSPILOT_KEY}"},
                json={"logs": [{
                    "service_name": record.name,
                    "severity": record.levelname.lower(),
                    "message": self.format(record),
                }]},
                timeout=5,
            )
        except Exception:
            pass

handler = OpsPilotHandler()
handler.setLevel(logging.WARNING)
logging.getLogger().addHandler(handler)`;
  }
  return `async function shipLog(message, { service = "web", severity = "error" } = {}) {
  await fetch("${ingestUrl}", {
    method: "POST",
    headers: {
      Authorization: "Bearer ${key}",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ logs: [{ service_name: service, severity, message }] }),
  });
}

// e.g. in your error handler:
// shipLog(err.stack, { service: "checkout", severity: "error" });`;
}
