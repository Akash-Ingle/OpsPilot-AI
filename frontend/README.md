# OpsPilot-AI Dashboard

Next.js 14 (App Router) + Tailwind dashboard for the [OpsPilot-AI](../backend) autonomous DevOps agent.

## Features

- **Incidents dashboard** — list of AI-analyzed incidents with severity badges, status pills, stat tiles (Total / Open / Investigating / Resolved / Critical), and filters synced to the URL.
- **Incident detail** — per-incident view with:
  - **Diagnosis** (issue, root cause, fix, confidence bar)
  - **Reasoning steps** — the agent's chain of thought
  - **Cited evidence** — log lines the LLM flagged as support
  - **Recent logs** with cited lines highlighted inline
  - **Agent telemetry** — iterations, duration, stop reason, low-confidence retries, confidence sparkline
  - **Tool usage timeline** — per-iteration tool dispatch with arguments, outcome, and duration

## Quickstart

```bash
# From the repo root
cd frontend

# 1. Install dependencies
npm install

# 2. Point the UI at your backend
cp .env.local.example .env.local
# edit NEXT_PUBLIC_API_URL if your backend isn't on http://localhost:8000/api/v1

# 3. Start the dev server
npm run dev
```

The app runs on [http://localhost:3000](http://localhost:3000). Make sure the FastAPI backend is running first (`cd backend && uvicorn app.main:app --reload`) — the backend already allows `http://localhost:3000` in `CORS_ORIGINS`.

## Scripts

| Command | Description |
| --- | --- |
| `npm run dev` | Start the Next.js dev server with hot reload. |
| `npm run build` | Production build. |
| `npm run start` | Serve the production build. |
| `npm run lint` | ESLint (Next.js + web-vitals rules). |
| `npm run type-check` | Strict `tsc --noEmit`. |

## Project layout

```
src/
  app/
    layout.tsx                       top bar + footer + Tailwind
    page.tsx                         /            — incidents dashboard
    loading.tsx                      dashboard skeleton
    error.tsx                        global error boundary
    not-found.tsx                    404
    incidents/[id]/
      page.tsx                       /incidents/:id  — incident detail
      loading.tsx                    detail skeleton
    globals.css
  components/
    SeverityBadge.tsx                colored severity pill
    StatusBadge.tsx                  incident status pill
    IncidentListItem.tsx             dashboard row card
    StatTile.tsx                     dashboard stat tile
    FilterBar.tsx                    client component: URL-synced filters
    PageHeader.tsx                   reusable page header
    Section.tsx                      titled card section
    ConfidenceBar.tsx                 confidence bar + threshold marker
    ReasoningSteps.tsx               ordered chain-of-thought list
    RelevantLogRefs.tsx              LLM-cited log references
    LogTable.tsx                     log table with highlight-by-id
    ObservabilityPanel.tsx           iterations/duration/sparkline
    ToolTimeline.tsx                 vertical tool-dispatch timeline
    EmptyState.tsx
  lib/
    api.ts                            thin fetch wrapper + ApiError
    types.ts                         TS mirrors of FastAPI schemas
    format.ts                        date/duration/confidence helpers
```

## Data flow

Pages are **server components**: they call the backend directly via `fetch` (with `cache: 'no-store'`) inside `src/lib/api.ts`. Only the filter bar is a client component — it uses `useRouter()` / `useSearchParams()` to sync filter state to the URL, which triggers a server re-render of the dashboard.

The UI binds directly to the backend response shapes:

- `GET /incidents` → `IncidentOut[]`
- `GET /incidents/{id}` → `IncidentDetail` (includes `analyses: AnalysisOut[]`)
- `GET /logs` → `LogOut[]`

`AnalysisOut.structured_output` carries the LLM contract (issue/root_cause/fix/severity/confidence/reasoning_steps/relevant_log_lines), and `AnalysisOut.observability` carries the agent telemetry rendered in the right-hand panel.

## Environment

| Variable | Default | Description |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000/api/v1` | Backend API base URL (with version prefix). |
