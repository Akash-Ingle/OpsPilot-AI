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
# unit + integration tests (no API key needed; the LLM is mocked)
pytest -q

# with coverage (as CI runs it)
pytest --cov=app --cov-report=term-missing
```

## Evaluate the agent

`scripts/run_eval.py` runs the multi-step agent against each seeded failure
scenario, scores it against ground truth, and prints accuracy + confidence
calibration. It calls a real LLM, so it needs a provider key in `.env`.

```bash
# from backend/, with an API key configured in .env
python scripts/run_eval.py                        # all scenarios, seeds 1,2,3
python scripts/run_eval.py --seeds 1 --threshold 0.7
python scripts/run_eval.py --json-out eval-report.json
```

Exit code is non-zero when overall accuracy falls below `--threshold`, so the
same script doubles as the regression signal used in CI.

## Roadmap

- **Week 1 (done):** backend skeleton, models, schemas, routes, log parser, rules-based anomaly detector.
- **Week 2:** LLM client, agent loop (`app/agent/orchestrator.py`), tool dispatch, `/analyze` wiring.
- **Week 3:** Next.js frontend + API integration.
- **Week 4:** Vector-DB incident memory, evaluation harness, polish.
