"""API route modules."""

from fastapi import APIRouter

from app.api.routes import (
    analyze,
    auth,
    evaluate,
    incidents,
    ingest,
    logs,
    projects,
    simulate,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(logs.router, prefix="/logs", tags=["logs"])
api_router.include_router(incidents.router, prefix="/incidents", tags=["incidents"])
api_router.include_router(analyze.router, prefix="/analyze", tags=["analyze"])
api_router.include_router(simulate.router, prefix="/simulate", tags=["simulate"])
api_router.include_router(evaluate.router, prefix="/evaluate", tags=["evaluate"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
