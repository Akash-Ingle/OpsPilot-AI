"""API route modules."""

from fastapi import APIRouter

from app.api.routes import analyze, evaluate, incidents, logs, simulate

api_router = APIRouter()
api_router.include_router(logs.router, prefix="/logs", tags=["logs"])
api_router.include_router(incidents.router, prefix="/incidents", tags=["incidents"])
api_router.include_router(analyze.router, prefix="/analyze", tags=["analyze"])
api_router.include_router(simulate.router, prefix="/simulate", tags=["simulate"])
api_router.include_router(evaluate.router, prefix="/evaluate", tags=["evaluate"])
