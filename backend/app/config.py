"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "OpsPilot-AI"
    app_env: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    host: str = "0.0.0.0"
    port: int = 8000

    database_url: str = "sqlite:///./opspilot.db"
    redis_url: str = "redis://localhost:6379/0"

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    llm_provider: str = "anthropic"  # "anthropic" | "openai" | "gemini"
    llm_model: str = "claude-3-5-sonnet-latest"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 1024
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    llm_min_confidence: float = 0.6  # below this, the agent loop forces another iteration

    vector_db_path: str = "./.chroma"

    # Session cookie hardening. Secure must be on in production (HTTPS); kept off
    # by default so http://localhost dev and the test client work.
    session_cookie_secure: bool = False
    session_cookie_samesite: str = "lax"

    # Per-IP rate limiting (protects the paid LLM endpoints on a public demo).
    # Limits use slowapi syntax, e.g. "10/minute" or "100/hour;1000/day".
    rate_limit_enabled: bool = True
    rate_limit_analyze: str = "10/minute"
    rate_limit_simulate: str = "20/minute"
    rate_limit_ingest: str = "120/minute"
    rate_limit_project_create: str = "10/hour"
    # Throttle credential endpoints to blunt brute-force / signup abuse.
    rate_limit_auth: str = "10/minute"

    # Public-demo safety net: when the live LLM call fails (e.g. the free-tier
    # daily quota is exhausted), fall back to a pre-computed analysis for the
    # matching built-in scenario instead of returning an error. Off by default
    # so local/dev surfaces real errors; enabled on the hosted demo.
    demo_cache_enabled: bool = False

    # --- Ingestion + always-on watcher --------------------------------------
    # Max log lines accepted in a single /ingest batch.
    ingest_max_batch: int = 1000
    # When logs arrive and anomalies are detected, automatically run the agent
    # and open an incident (the "always-on" behavior). The cooldown throttles
    # this per project so a log flood can't spam the LLM / burn free-tier quota.
    auto_analyze_enabled: bool = True
    auto_analyze_cooldown_seconds: int = 300
    # How many recent logs the watcher feeds the agent per project.
    auto_analyze_window: int = 300
    # Public dashboard base URL, used to build incident links in Slack alerts.
    frontend_base_url: str = ""

    # Stored as a raw string in the env so pydantic-settings doesn't try to
    # JSON-decode it. Consumers should read `settings.cors_origins` (the
    # property below) to get the parsed list. Reads the `CORS_ORIGINS` env var.
    cors_origins_raw: str = Field(
        default="http://localhost:3000",
        validation_alias="CORS_ORIGINS",
    )

    @property
    def cors_origins(self) -> List[str]:
        """Comma-separated origins, parsed into a list at access time."""
        return [
            origin.strip()
            for origin in (self.cors_origins_raw or "").split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


settings = get_settings()
