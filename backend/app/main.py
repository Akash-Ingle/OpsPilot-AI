"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import api_router
from app.config import settings
from app.core.logging import configure_logging, logger
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("Starting {} v{} (env={})", settings.app_name, __version__, settings.app_env)
    init_db()
    logger.info("Database initialized")
    yield
    logger.info("Shutting down {}", settings.app_name)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Autonomous DevOps AI agent - log analysis, anomaly detection, and multi-step LLM reasoning.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/", tags=["meta"])
    def root():
        return {
            "name": settings.app_name,
            "version": __version__,
            "env": settings.app_env,
            "docs": "/docs",
            "api": settings.api_v1_prefix,
        }

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok"}

    return app


app = create_app()
