"""
Structured logging via structlog.

Usage:
    from src.utils.logger import get_logger

    log = get_logger("image_pipeline")
    log.info("step_complete", sku="TAKI-0001", step="bg_remove")
"""

import logging
import sys

import structlog

from src.config.settings import Settings

_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return

    settings = Settings()
    level = logging.getLevelName(settings.LOG_LEVEL.upper())
    is_dev = settings.LOG_LEVEL.upper() in ("DEBUG", "INFO")

    processors: list[structlog.types.Processor] = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if is_dev:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Keep stdlib at the same level for third-party libraries
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
        level=level,
    )

    _configured = True


def get_logger(module: str) -> structlog.types.FilteringBoundLogger:
    """Return a structlog bound logger pre-tagged with *module*."""
    _configure()
    return structlog.get_logger(module=module)
