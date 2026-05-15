"""
config.py — Application settings loaded from environment variables
"""
from __future__ import annotations

import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "ASCII Stream Backend"
    debug: bool = False
    log_level: str = "INFO"

    # Auth
    jwt_secret: str = "change-me-in-production-please"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # Session
    session_ttl_seconds: int = 600        # 10 min idle → evict
    session_cleanup_interval: int = 60    # GC every 60s
    max_sessions_per_ip: int = 10

    # Backpressure
    default_max_fps: int = 15
    frame_queue_maxsize: int = 2
    worker_concurrency: int = 4
    max_frame_bytes: int = 2 * 1024 * 1024  # 2 MB

    # Redis (optional)
    redis_url: str = "redis://localhost:6379/0"
    use_redis: bool = False

    # Storage
    snapshot_backend: str = "local"       # "local" | "s3"
    snapshot_local_dir: str = "/tmp/ascii_snapshots"
    s3_bucket: str = ""
    s3_region: str = "us-east-1"

    # Rate limits
    rate_limit_session_create: str = "10/minute"
    rate_limit_ws_connect: str = "20/minute"


@lru_cache
def get_settings() -> Settings:
    return Settings()