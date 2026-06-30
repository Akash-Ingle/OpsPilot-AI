/**
 * TypeScript counterparts of the FastAPI Pydantic schemas.
 *
 * Keep these in sync with `backend/app/schemas/*.py`. The shapes below are
 * the wire format (JSON), not the ORM, so enums are plain strings.
 */

export interface User {
  id: number;
  email: string;
}

export type Severity = "low" | "medium" | "high" | "critical";

export type IncidentStatus =
  | "open"
  | "investigating"
  | "resolved"
  | "closed"
  | "dismissed";

// --- Logs -------------------------------------------------------------------

export interface LogOut {
  id: number;
  timestamp: string; // ISO-8601
  service_name: string;
  severity: string;
  message: string;
  created_at: string;
}

// --- Analysis / LLM structured output --------------------------------------

export interface LogReference {
  log_id?: number | null;
  line_index?: number | null;
  excerpt?: string | null;
  reason?: string | null;
}

export interface LLMStructuredOutput {
  issue: string;
  root_cause: string;
  fix: string;
  severity: Severity;
  confidence: number;
  needs_more_data: boolean;
  requested_action: string;
  requested_action_args: Record<string, unknown>;
  reasoning_steps: string[];
  relevant_log_lines: LogReference[];
}

// --- Agent observability ----------------------------------------------------

export type StoppedReason =
  | "confident"
  | "max_iterations"
  | "no_progress"
  | "low_confidence_final";

export interface ToolCallRecord {
  step: number;
  name: string;
  args: Record<string, unknown>;
  ok: boolean;
  error?: string | null;
  duration_ms: number;
}

export interface IterationRecord {
  step: number;
  confidence: number;
  severity: string;
  needs_more_data: boolean;
  requested_action: string;
  low_confidence_retry: boolean;
  tool_call?: ToolCallRecord | null;
  duration_ms: number;
}

export interface AgentObservability {
  iterations: number;
  max_iterations: number;
  duration_ms: number;
  started_at: string;
  finished_at: string;
  stopped_reason: StoppedReason;
  low_confidence_retries: number;
  confidence_progression: number[];
  tools_called: ToolCallRecord[];
  iteration_trace: IterationRecord[];
}

export interface AnalysisOut {
  id: number;
  incident_id: number;
  step_index: number;
  llm_output: string;
  structured_output?: LLMStructuredOutput | null;
  confidence_score?: number | null;
  observability?: AgentObservability | null;
  created_at: string;
}

// --- Incidents --------------------------------------------------------------

export interface IncidentOut {
  id: number;
  title: string;
  severity: Severity;
  status: IncidentStatus;
  root_cause: string | null;
  suggested_fix: string | null;
  detected_at: string;
  updated_at: string;
}

export interface IncidentDetail extends IncidentOut {
  analyses: AnalysisOut[];
}

// --- Simulation / analysis triggers ----------------------------------------

export interface ScenarioInfo {
  name: string;
  description: string;
  default_duration_min: number;
  default_service: string;
}

export interface SimulateResult {
  scenario: string;
  persisted: boolean;
  count: number;
}

export interface AnalyzeResult {
  incident_id: number;
  analysis_id: number;
  steps_run: number;
  logs_analyzed: number;
  anomalies_detected: number;
  final: LLMStructuredOutput;
  observability: AgentObservability;
}

// --- Projects / ingestion (connect-your-app loop) --------------------------

export interface ProjectCreated {
  id: number;
  name: string;
  api_key: string; // shown only once
  key_prefix: string;
}

export interface ProjectOut {
  id: number;
  name: string;
  key_prefix: string;
  alerts_enabled: boolean;
  slack_configured: boolean;
  last_auto_analysis_at: string | null;
  log_count: number;
  incident_count: number;
  created_at: string;
}

export interface IngestResult {
  ingested: number;
  project_id: number;
  watcher_scheduled: boolean;
}
