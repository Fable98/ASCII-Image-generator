"""
main.py — FastAPI application bootstrap for ASCII Stream Backend
"""
from __future__ import annotations

import signal
import time
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from src.api import health, sessions, ws
from src.api.sessions import auth_router, snapshots_router
from src.config import get_settings
from src.observability.logging_config import configure_logging
from src.services.session_manager import get_session_manager

log = structlog.get_logger(__name__)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Configure structured logging
    configure_logging(
        log_level=settings.log_level,
        json_logs=not settings.debug,
    )

    log.info("app.starting", name=settings.app_name, debug=settings.debug)

    # Start session manager (GC loop)
    manager = get_session_manager()
    await manager.start(
        ttl_seconds=settings.session_ttl_seconds,
        interval=settings.session_cleanup_interval,
    )

    # Ensure snapshot dir exists
    import os
    os.makedirs(settings.snapshot_local_dir, exist_ok=True)

    log.info("app.ready")
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    log.info("app.shutting_down")
    await manager.stop()
    log.info("app.stopped")


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="ASCII Stream Backend",
        description=(
            "Realtime video-to-ASCII streaming over WebSocket. "
            "Send frames, receive art."
        ),
        version="1.0.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request timing middleware ──────────────────────────────────────────────
    @app.middleware("http")
    async def add_timing_header(request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.2f}"
        return response

    # ── Global exception handler ───────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        log.exception("unhandled_error", path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(auth_router)
    app.include_router(sessions.router)
    app.include_router(snapshots_router)
    app.include_router(ws.router)

    # ── Prometheus metrics endpoint ────────────────────────────────────────────
    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics():
        return PlainTextResponse(
            generate_latest().decode("utf-8"),
            media_type=CONTENT_TYPE_LATEST,
        )

    # ── Root ──────────────────────────────────────────────────────────────────
    @app.get("/", include_in_schema=False)
    async def root():
        return {
            "service": "ASCII Stream Backend",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/health/live",
        }

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=get_settings().debug,
        log_level="info",
    )