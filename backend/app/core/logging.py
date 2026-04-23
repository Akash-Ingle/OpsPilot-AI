"""Centralized logging configuration using loguru."""

import sys

from loguru import logger

from app.config import settings


def configure_logging() -> None:
    """Configure the global logger once at application startup."""
    logger.remove()
    logger.add(
        sys.stdout,
        level="DEBUG" if settings.debug else "INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        backtrace=settings.debug,
        diagnose=settings.debug,
    )


__all__ = ["configure_logging", "logger"]
