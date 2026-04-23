# OpsPilot-AI Backend

FastAPI service for the autonomous DevOps AI agent: log ingestion, anomaly
detection, and multi-step LLM reasoning.

## Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI entry point + lifespan
│   ├── config.py            # Settings (env-driven)
│   ├── database.py          # SQLAlchemy engine, session, Base
│   ├── models/              # ORM: Log, Incident, Analysis
│   ├── schemas/             # Pydantic request/response models
│   ├── api/
│   │   ├── deps.py          # DB session dependency
│   │   └── routes/          # logs, incidents, analyze
│   ├── services/            # log_parser, anomaly_detector
│   ├── agent/               # prompts, tools, orchestrator (Week 2)
│   └── core/logging.py
└── tests/
```

## Quickstart

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # edit DATABASE_URL / LLM keys as needed
```

For zero-setup local dev, the default `DATABASE_URL` in `.env.example` falls
back to SQLite. For production use the Postgres URL.

## Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then visit:
- API root: http://localhost:8000/
- Interactive docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

## API (v1)

Base prefix: `/api/v1`

| Method | Path                       | Description                           |
| ------ | -------------------------- | ------------------------------------- |
| POST   | `/logs/upload`             | Upload logs (text or JSON)            |
| GET    | `/logs`                    | List/filter ingested logs             |
| GET    | `/incidents`               | List incidents                        |
| POST   | `/incidents`               | Create incident (manual)              |
| GET    | `/incidents/{id}`          | Incident detail + analysis trace      |
| PATCH  | `/incidents/{id}`          | Update an incident                    |
| POST   | `/analyze`                 | Trigger agent analysis (Week 2)       |

## Test

```bash
pytest -q
```

## Roadmap

- **Week 1 (done):** backend skeleton, models, schemas, routes, log parser, rules-based anomaly detector.
- **Week 2:** LLM client, agent loop (`app/agent/orchestrator.py`), tool dispatch, `/analyze` wiring.
- **Week 3:** Next.js frontend + API integration.
- **Week 4:** Vector-DB incident memory, evaluation harness, polish.
