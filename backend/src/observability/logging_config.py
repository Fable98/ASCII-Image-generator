"""
logging_config.py — Structlog configuration for console and JSON logging
"""
from __future__ import annotations

import logging
import sys
import structlog

def configure_logging(log_level: str = "INFO", json_logs: bool = False):
    # Convert string log level to standard logging constants
    level_num = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    if json_logs:
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(),
        ]

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level_num),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging root logger
    logging.basicConfig(
        level=level_num,
        format="%(message)s",
        stream=sys.stdout,
        force=True,
    )
