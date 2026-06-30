/**
 * Thin fetch wrapper around the OpsPilot-AI backend.
 *
 * Auth model:
 *  - The BROWSER calls a SAME-ORIGIN proxy (`/api/v1/*`, see next.config.js).
 *    The backend's httpOnly session cookie is therefore first-party and rides
 *    along automatically on every browser request.
 *  - SERVER components call the backend directly (absolute URL) and must forward
 *    the incoming session cookie explicitly (read via next/headers and passed in
 *    as `cookie`), since there's no browser to attach it.
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
  User,
} from "./types";

// Absolute backend URL for EXTERNAL clients (shown in the Connect snippets and
// the API-docs link). Not used for in-app browser fetches.
export const PUBLIC_BACKEND_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ||
  "http://localhost:8000/api/v1";

// Server-side base: the Next server reaches the backend directly. Prefer an
// internal URL (Docker network) when provided, else the public URL.
const SERVER_BASE =
  process.env.INTERNAL_API_URL?.replace(/\/$/, "") || PUBLIC_BACKEND_URL;

// Browser-side base: relative, so requests are same-origin and get proxied to
// the backend by Next (keeping the session cookie first-party).
const BROWSER_BASE = "/api/v1";

const isServer = typeof window === "undefined";
const API_URL = isServer ? SERVER_BASE : BROWSER_BASE;

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
// first request then returns a gateway error for ~30-60s while it cold-starts.
// Retry idempotent reads with backoff. POSTs are never retried.
const TRANSIENT_STATUSES = new Set([502, 503, 504]);
const RETRY_DELAYS_MS = [3000, 5000, 8000, 10000, 12000, 15000];

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// FastAPI's error `detail` may be a string (HTTPException) or a list of objects
// (422 validation errors). Render it to a readable string.
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

interface RequestOpts {
  // Server-only: forward this Cookie header to the backend so the session is
  // recognized during SSR. Ignored in the browser (cookies are automatic).
  cookie?: string | null;
  // Opt-in for non-GET requests: retry through transient cold-start failures.
  // Safe only for operations that are idempotent in practice (the request never
  // reached the app on a gateway error, so re-sending can't double-apply).
  retryTransient?: boolean;
}

// A failure is "transient" (worth retrying) when it's a gateway error, OR a 500
// whose body is NOT our JSON error envelope. The latter is how the Next.js
// same-origin proxy reports an unreachable upstream during a cold start: it
// returns 500 with an HTML body, whereas our backend always returns JSON.
function isTransientFailure(status: number, isJson: boolean): boolean {
  return TRANSIENT_STATUSES.has(status) || (status === 500 && !isJson);
}

async function request<T>(
  path: string,
  init?: RequestInit,
  opts?: RequestOpts,
): Promise<T> {
  const url = `${API_URL}${path}`;
  const method = (init?.method ?? "GET").toUpperCase();
  const canRetry = method === "GET" || opts?.retryTransient === true;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  // Server-only: forward the session cookie (no browser to attach it).
  if (isServer && opts?.cookie) headers.Cookie = opts.cookie;

  let attempt = 0;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    let res: Response;
    try {
      res = await fetch(url, {
        cache: "no-store",
        // Send cookies on same-origin browser requests (the session lives here).
        credentials: "include",
        ...init,
        // Headers come AFTER ...init so Content-Type / Cookie aren't clobbered.
        headers,
      });
    } catch (err) {
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

    const contentType = res.headers.get("content-type") ?? "";
    const isJson = contentType.includes("application/json");

    if (
      !res.ok &&
      canRetry &&
      isTransientFailure(res.status, isJson) &&
      attempt < RETRY_DELAYS_MS.length
    ) {
      await sleep(RETRY_DELAYS_MS[attempt++]);
      continue;
    }

    const payload = isJson
      ? await res.json().catch(() => null)
      : await res.text();

    if (!res.ok) {
      const detail =
        (isJson ? extractDetail(payload) : null) ??
        (isTransientFailure(res.status, isJson)
          ? "The backend is waking up (free-tier cold start). Please try again in a moment."
          : `${res.status} ${res.statusText}`);
      throw new ApiError(detail, res.status, url, payload);
    }

    return (payload === "" ? (undefined as T) : (payload as T));
  }
}

// ---------------------------------------------------------------------------
// Auth (human accounts; session via httpOnly cookie)
// ---------------------------------------------------------------------------

export function register(email: string, password: string): Promise<User> {
  return request<User>(
    `/auth/register`,
    { method: "POST", body: JSON.stringify({ email, password }) },
    { retryTransient: true },
  );
}

export function login(email: string, password: string): Promise<User> {
  return request<User>(
    `/auth/login`,
    { method: "POST", body: JSON.stringify({ email, password }) },
    { retryTransient: true },
  );
}

export function logout(): Promise<void> {
  return request<void>(`/auth/logout`, { method: "POST" });
}

export function getMe(cookie?: string | null): Promise<User> {
  return request<User>(`/auth/me`, undefined, { cookie });
}

// ---------------------------------------------------------------------------
// Incidents (reads scoped to the caller's projects; SSR forwards the cookie)
// ---------------------------------------------------------------------------

export interface ListIncidentsParams {
  status?: IncidentStatus;
  severity?: Severity;
  limit?: number;
  offset?: number;
}

export function listIncidents(
  params: ListIncidentsParams = {},
  cookie?: string | null,
): Promise<IncidentOut[]> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.severity) qs.set("severity", params.severity);
  qs.set("limit", String(params.limit ?? 50));
  qs.set("offset", String(params.offset ?? 0));
  return request<IncidentOut[]>(`/incidents?${qs.toString()}`, undefined, {
    cookie,
  });
}

export function getIncident(
  id: number | string,
  cookie?: string | null,
): Promise<IncidentDetail> {
  return request<IncidentDetail>(`/incidents/${id}`, undefined, { cookie });
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
  cookie?: string | null,
): Promise<LogOut[]> {
  const qs = new URLSearchParams();
  if (params.service_name) qs.set("service_name", params.service_name);
  if (params.severity) qs.set("severity", params.severity);
  qs.set("limit", String(params.limit ?? 100));
  qs.set("offset", String(params.offset ?? 0));
  return request<LogOut[]>(`/logs?${qs.toString()}`, undefined, { cookie });
}

// ---------------------------------------------------------------------------
// Simulation + analysis (browser write actions; session cookie is automatic)
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
  return request<SimulateResult>(
    `/simulate`,
    { method: "POST", body: JSON.stringify(params) },
    { retryTransient: true },
  );
}

export interface AnalyzeParams {
  service_name?: string;
  limit?: number;
  max_steps?: number;
}

export function triggerAnalysis(
  params: AnalyzeParams = {},
): Promise<AnalyzeResult> {
  return request<AnalyzeResult>(
    `/analyze`,
    { method: "POST", body: JSON.stringify(params) },
    { retryTransient: true },
  );
}

// ---------------------------------------------------------------------------
// Projects (owned by the logged-in user; authenticated via the session cookie)
// ---------------------------------------------------------------------------

export function listProjects(cookie?: string | null): Promise<ProjectOut[]> {
  return request<ProjectOut[]>(`/projects`, undefined, { cookie });
}

export function createProject(name: string): Promise<ProjectCreated> {
  return request<ProjectCreated>(`/projects`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export interface UpdateProjectParams {
  slack_webhook_url?: string;
  alerts_enabled?: boolean;
}

export function updateProjectById(
  id: number,
  params: UpdateProjectParams,
): Promise<ProjectOut> {
  return request<ProjectOut>(`/projects/${id}`, {
    method: "PATCH",
    body: JSON.stringify(params),
  });
}

export function deleteProject(id: number): Promise<void> {
  return request<void>(`/projects/${id}`, { method: "DELETE" });
}

export function sendTestAlert(
  id: number,
): Promise<{ ok: boolean; detail: string }> {
  return request<{ ok: boolean; detail: string }>(
    `/projects/${id}/test-alert`,
    { method: "POST" },
  );
}

// ---------------------------------------------------------------------------
// Ingestion — authenticated with the per-project API KEY (machine credential).
// Used by the "send sample logs" demo button; real apps call the backend URL
// directly from their own code.
// ---------------------------------------------------------------------------

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
    headers: { Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({ logs }),
  });
}

export { API_URL };
