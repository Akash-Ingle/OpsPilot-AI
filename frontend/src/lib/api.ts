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
  LogOut,
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_URL}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      // Never cache — incident state is volatile.
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      ...init,
    });
  } catch (err) {
    // Network-level error (backend down, CORS blocked, DNS, etc.)
    throw new ApiError(
      `Network error contacting backend at ${url}: ${(err as Error).message}`,
      0,
      url,
      null,
    );
  }

  const contentType = res.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await res.json().catch(() => null) : await res.text();

  if (!res.ok) {
    const detail =
      (isJson && payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : null) ?? `${res.status} ${res.statusText}`;
    throw new ApiError(detail, res.status, url, payload);
  }

  return payload as T;
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

export function listIncidents(
  params: ListIncidentsParams = {},
): Promise<IncidentOut[]> {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.severity) qs.set("severity", params.severity);
  qs.set("limit", String(params.limit ?? 50));
  qs.set("offset", String(params.offset ?? 0));
  return request<IncidentOut[]>(`/incidents?${qs.toString()}`);
}

export function getIncident(id: number | string): Promise<IncidentDetail> {
  return request<IncidentDetail>(`/incidents/${id}`);
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

export function listLogs(params: ListLogsParams = {}): Promise<LogOut[]> {
  const qs = new URLSearchParams();
  if (params.service_name) qs.set("service_name", params.service_name);
  if (params.severity) qs.set("severity", params.severity);
  qs.set("limit", String(params.limit ?? 100));
  qs.set("offset", String(params.offset ?? 0));
  return request<LogOut[]>(`/logs?${qs.toString()}`);
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

export { API_URL };
