/**
 * Thin fetch wrapper around the OpsPilot-AI backend.
 *
 * Usage is identical in server components and route handlers: just await the
 * helpers below. All fetches disable Next's cache so the dashboard reflects
 * new incidents as soon as the backend persists them.
 */

import type {
  AnalyzeResult,
  IncidentDetail,
  IncidentOut,
  IncidentStatus,
  IngestResult,
  LogOut,
  ProjectCreated,
  ProjectOut,
  ScenarioInfo,
  Severity,
  SimulateResult,
} from "./types";

// Base URL used by the browser (inlined into the client bundle at build time).
const PUBLIC_API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ||
  "http://localhost:8000/api/v1";

// In containerized setups the Next server and the browser reach the backend at
// different hostnames (e.g. `http://backend:8000` inside the Docker network vs.
// `http://localhost:8000` from the user's browser). When `INTERNAL_API_URL` is
// set, server-side requests use it; the browser always uses the public URL.
const INTERNAL_API_URL = process.env.INTERNAL_API_URL?.replace(/\/$/, "");

const API_URL =
  typeof window === "undefined" && INTERNAL_API_URL
    ? INTERNAL_API_URL
    : PUBLIC_API_URL;

// Name of the cookie that mirrors the per-browser API key. The Connect page
// writes it (alongside localStorage) so the server-rendered dashboard / detail
// pages can read it via next/headers and forward it to the tenant-scoped API.
export const KEY_COOKIE = "opspilot_key";

export class ApiError extends Error {
  readonly status: number;
  readonly url: string;
  readonly body: unknown;

  constructor(message: string, status: number, url: string, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.url = url;
    this.body = body;
  }
}

// Free-tier hosts (e.g. Render) spin the backend down after inactivity; the
// first request then returns a gateway error (or a connection failure) for
// ~30-60s while it cold-starts. Retry idempotent reads with backoff so the page
// waits out the wake-up instead of showing an error. POSTs are never retried —
// re-sending /simulate or /analyze could double-write logs or double-spend the
// LLM quota.
const TRANSIENT_STATUSES = new Set([502, 503, 504]);
const RETRY_DELAYS_MS = [3000, 5000, 8000, 10000, 12000, 15000];

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// FastAPI's error `detail` may be a string (HTTPException) or a list of objects
// (422 validation errors). Render it to a readable string instead of letting an
// object stringify to "[object Object]".
function extractDetail(payload: unknown): string | null {
  if (!payload || typeof payload !== "object" || !("detail" in payload)) {
    return null;
  }
  const d = (payload as { detail: unknown }).detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return (
      d
        .map((e) =>
          e && typeof e === "object" && "msg" in e
            ? String((e as { msg: unknown }).msg)
            : JSON.stringify(e),
        )
        .join("; ") || null
    );
  }
  if (d && typeof d === "object" && "msg" in d) {
    return String((d as { msg: unknown }).msg);
  }
  return d == null ? null : String(d);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_URL}${path}`;
  const method = (init?.method ?? "GET").toUpperCase();
  const canRetry = method === "GET";

  let attempt = 0;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    let res: Response;
    try {
      res = await fetch(url, {
        // Never cache — incident state is volatile.
        cache: "no-store",
        ...init,
        // Headers must come AFTER ...init: spreading init last would clobber the
        // merged headers and drop Content-Type for calls that pass an Authorization
        // header (e.g. /ingest, PATCH /projects/me), causing the backend to reject
        // the JSON body.
        headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      });
    } catch (err) {
      // Network-level error (backend down/cold, CORS blocked, DNS, etc.)
      if (canRetry && attempt < RETRY_DELAYS_MS.length) {
        await sleep(RETRY_DELAYS_MS[attempt++]);
        continue;
      }
      throw new ApiError(
        `Network error contacting backend at ${url}: ${(err as Error).message}`,
        0,
        url,
        null,
      );
    }

    // Transient gateway error from a cold backend: back off and retry.
    if (
      !res.ok &&
      canRetry &&
      TRANSIENT_STATUSES.has(res.status) &&
      attempt < RETRY_DELAYS_MS.length
    ) {
      await sleep(RETRY_DELAYS_MS[attempt++]);
      continue;
    }

    const contentType = res.headers.get("content-type") ?? "";
    const isJson = contentType.includes("application/json");
    const payload = isJson
      ? await res.json().catch(() => null)
      : await res.text();

    if (!res.ok) {
      const detail =
        (isJson ? extractDetail(payload) : null) ??
        `${res.status} ${res.statusText}`;
      throw new ApiError(detail, res.status, url, payload);
    }

    return payload as T;
  }
}

// ---------------------------------------------------------------------------
// Incidents
// ---------------------------------------------------------------------------

export interface ListIncidentsParams {
  status?: IncidentStatus;
  severity?: Severity;
  limit?: number;
  offset?: number;
}

// Read endpoints are tenant-scoped: with no key the backend returns only the
// public sandbox (project_id NULL); with a valid key it returns that project's
// rows. The dashboard/detail pages forward the per-browser key when present.
function maybeAuth(apiKey?: string | null): Record<string, string> {
  return apiKey ? { Authorization: `Bearer ${apiKey}` } : {};
}

export function listIncidents(
  params: ListIncidentsParams = {},
  apiKey?: string | null,
): Promise<IncidentOut[]> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.severity) qs.set("severity", params.severity);
  qs.set("limit", String(params.limit ?? 50));
  qs.set("offset", String(params.offset ?? 0));
  return request<IncidentOut[]>(`/incidents?${qs.toString()}`, {
    headers: maybeAuth(apiKey),
  });
}

export function getIncident(
  id: number | string,
  apiKey?: string | null,
): Promise<IncidentDetail> {
  return request<IncidentDetail>(`/incidents/${id}`, {
    headers: maybeAuth(apiKey),
  });
}

// ---------------------------------------------------------------------------
// Logs
// ---------------------------------------------------------------------------

export interface ListLogsParams {
  service_name?: string;
  severity?: string;
  limit?: number;
  offset?: number;
}

export function listLogs(
  params: ListLogsParams = {},
  apiKey?: string | null,
): Promise<LogOut[]> {
  const qs = new URLSearchParams();
  if (params.service_name) qs.set("service_name", params.service_name);
  if (params.severity) qs.set("severity", params.severity);
  qs.set("limit", String(params.limit ?? 100));
  qs.set("offset", String(params.offset ?? 0));
  return request<LogOut[]>(`/logs?${qs.toString()}`, {
    headers: maybeAuth(apiKey),
  });
}

// ---------------------------------------------------------------------------
// Simulation + analysis (write actions, used by the in-browser demo flow)
// ---------------------------------------------------------------------------

export function listScenarios(): Promise<ScenarioInfo[]> {
  return request<ScenarioInfo[]>(`/simulate/scenarios`);
}

export interface SimulateParams {
  scenario: string;
  seed?: number;
  service?: string;
  duration_minutes?: number;
}

export function simulateScenario(
  params: SimulateParams,
): Promise<SimulateResult> {
  return request<SimulateResult>(`/simulate`, {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export interface AnalyzeParams {
  service_name?: string;
  limit?: number;
  max_steps?: number;
}

export function triggerAnalysis(
  params: AnalyzeParams = {},
): Promise<AnalyzeResult> {
  return request<AnalyzeResult>(`/analyze`, {
    method: "POST",
    body: JSON.stringify(params),
  });
}

// ---------------------------------------------------------------------------
// Projects + ingestion (the "connect your app" loop)
//
// These are client-side calls authenticated with a per-project API key. The key
// is held only in the browser (localStorage) — it never touches the Next server.
// ---------------------------------------------------------------------------

function authHeaders(apiKey: string): Record<string, string> {
  return { Authorization: `Bearer ${apiKey}` };
}

export function createProject(name: string): Promise<ProjectCreated> {
  return request<ProjectCreated>(`/projects`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function getProject(apiKey: string): Promise<ProjectOut> {
  return request<ProjectOut>(`/projects/me`, { headers: authHeaders(apiKey) });
}

export interface UpdateProjectParams {
  slack_webhook_url?: string;
  alerts_enabled?: boolean;
}

export function updateProject(
  apiKey: string,
  params: UpdateProjectParams,
): Promise<ProjectOut> {
  return request<ProjectOut>(`/projects/me`, {
    method: "PATCH",
    headers: authHeaders(apiKey),
    body: JSON.stringify(params),
  });
}

export interface IngestLogItem {
  message: string;
  service_name?: string;
  severity?: string;
  timestamp?: string;
}

export function ingestLogs(
  apiKey: string,
  logs: IngestLogItem[],
): Promise<IngestResult> {
  return request<IngestResult>(`/ingest`, {
    method: "POST",
    headers: authHeaders(apiKey),
    body: JSON.stringify({ logs }),
  });
}

export { API_URL };
