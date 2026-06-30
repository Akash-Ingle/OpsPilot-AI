# Design decisions & trade-offs

This document captures the *why* behind OpsPilot-AI's architecture — the choices
that aren't obvious from reading the code, and what I'd change at larger scale.

## 1. Push, not pull: an event-driven watcher

The product thesis is that a chat box is *pull* (you must already know something
broke, then paste the right lines), while OpsPilot is *push*: it watches the
stream and tells you.

- **Decision:** auto-analysis runs as a FastAPI **background task** scheduled by
  the `/ingest` route, not a polling cron or a separate worker process.
- **Why:** it stays event-driven and works on a free-tier host that sleeps
  between requests (no always-on scheduler needed), which keeps the public demo
  at $0.
- **Trade-off:** background tasks are in-process — if the host restarts mid-task
  the analysis is dropped (the next ingest re-triggers it). At scale this moves
  to a durable queue (Celery/RQ/Kafka) with retries and a dedicated worker pool.
- **Guardrail:** a per-project **cooldown** caps auto-analysis to once per
  window, so a burst of logs can't fan out into a flood of LLM calls.

## 2. Multi-step agent with explicit, observable termination

The orchestrator doesn't make one LLM call — it loops until confident.

- Each iteration returns strict, Pydantic-validated JSON (issue, root cause, fix,
  severity, confidence, ordered reasoning steps, cited log ids).
- The loop continues if the model is **low-confidence** or **requests a tool**
  (`fetch_logs`, `get_metrics`, `restart_service`, `scale_service`, dispatched
  with validated args), and stops on `confident`, `max_iterations`, or
  `low_confidence_final`.
- Every run emits an **observability** payload (per-iteration confidence,
  severity, tool calls + latency, confidence progression, `stopped_reason`)
  surfaced in the dashboard. This is what makes the agent debuggable rather than
  a black box.

## 3. Tenant isolation: 404, never 403

- Reads are scoped by the caller's identity: anonymous → a shared public sandbox
  (`project_id IS NULL`); a session → the user's own projects; an API key → that
  one project.
- **Cross-tenant access returns 404, not 403**, so the API never leaks that a
  resource exists to someone not allowed to see it.
- **Credentials at rest:** API keys are stored only as **SHA-256 hashes** (raw
  key shown once); passwords are **bcrypt**-hashed.

## 4. Sessions over a same-origin proxy (XSS-resistant auth)

- The browser dashboard authenticates with a server-side **session in an
  httpOnly, Secure, SameSite=Lax cookie** — never a token in `localStorage`.
- The Next.js frontend proxies `/api/v1/*` to the backend (a `rewrites()` rule),
  so the cookie is **first-party** and rides along automatically. Page
  JavaScript can't read it, which closes the usual token-exfiltration XSS vector.
- **Trade-off:** the proxy adds a hop and couples the two services' origins; the
  upside is materially better auth security for a public deployment.

## 5. Degrade, don't fail

A public demo on a free LLM tier *will* hit quota. The system is built so a
failure in a non-critical path never breaks the critical one:

- **LLM quota exhausted →** serve a pre-computed analysis for the matching
  scenario, flagged `served_from_cache`, instead of a 500.
- **Slack webhook fails →** logged and swallowed; ingestion/analysis is
  unaffected.
- **Vector-memory write fails →** best-effort; the incident is still persisted.
- **Cold-start gateway errors →** the frontend retries transient failures
  (502/503/504, and a non-JSON 500 from the proxy) with backoff for idempotent
  and demo actions.

## 6. Storage: SQLite → Postgres, Chroma for memory

- SQLAlchemy 2 with a connection string that's **SQLite for zero-setup dev** and
  **Postgres in production** (normalized + `pool_pre_ping` for dropped
  connections). Lightweight column-ensure migrations run at startup.
- Diagnosed incidents are embedded into **ChromaDB** so future analyses retrieve
  similar past incidents as grounding context — cheap "institutional memory."
- **Trade-off:** at scale, incident memory moves to a managed vector DB and the
  startup column-ensure is replaced by proper Alembic migrations (already a dep).

## What I'd do next at scale

- Durable task queue + worker pool for analysis (decouple from request lifecycle).
- Alembic migrations as the single source of truth for schema.
- Streaming log ingestion (push/SSE) and windowed anomaly detection over a
  time-series store rather than re-querying recent rows.
- Multi-channel alerting (PagerDuty/Opsgenie) behind the same best-effort
  interface used for Slack.
