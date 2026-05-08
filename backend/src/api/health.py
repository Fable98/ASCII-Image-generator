"""
health.py — Liveness and readiness health check endpoints
"""
from __future__ import annotations

import time
from typing import Any

import structlog
from fastapi import APIRouter, Response, status

from src.services.session_manager import get_session_manager

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/health", tags=["health"])

_start_time = time.monotonic()


@router.get("/live", status_code=status.HTTP_200_OK)
async def liveness():
    """
    Liveness probe — returns 200 as long as the process is alive.
    Kubernetes/Docker will restart the container if this fails.
    """
    return {
        "status": "ok",
        "uptime_seconds": round(time.monotonic() - _start_time, 1),
    }


@router.get("/ready")
async def readiness(response: Response):
    """
    Readiness probe — checks that all dependencies are reachable.
    Returns 200 when ready, 503 when degraded.
    Load balancer stops sending traffic on 503.
    """
    checks: dict[str, Any] = {}
    healthy = True

    # Check session manager
    try:
        manager = get_session_manager()
        checks["session_manager"] = {
            "status": "ok",
            "active_sessions": manager.active_count(),
        }
    except Exception as e:
        checks["session_manager"] = {"status": "error", "detail": str(e)}
        healthy = False

    # Check snapshot dir
    try:
        import os
        from src.config import get_settings
        settings = get_settings()
        os.makedirs(settings.snapshot_local_dir, exist_ok=True)
        checks["snapshot_store"] = {"status": "ok", "backend": settings.snapshot_backend}
    except Exception as e:
        checks["snapshot_store"] = {"status": "error", "detail": str(e)}
        healthy = False

    # Redis check (if enabled)
    try:
        from src.config import get_settings
        settings = get_settings()
        if settings.use_redis:
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.redis_url)
            await r.ping()
            await r.aclose()
            checks["redis"] = {"status": "ok"}
        else:
            checks["redis"] = {"status": "disabled"}
    except Exception as e:
        checks["redis"] = {"status": "error", "detail": str(e)}
        # Redis is optional — don't mark as unhealthy if not enabled
        from src.config import get_settings
        if get_settings().use_redis:
            healthy = False

    http_status = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    response.status_code = http_status

    return {
        "status": "ok" if healthy else "degraded",
        "checks": checks,
        "uptime_seconds": round(time.monotonic() - _start_time, 1),
    }