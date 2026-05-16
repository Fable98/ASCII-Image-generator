"""
schemas.py — Pydantic request/response models for ASCII Stream Backend
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ── RenderConfig ──────────────────────────────────────────────────────────────

class RenderConfig(BaseModel):
    flip_horizontal: bool = False
    flip_vertical: bool = False
    ascii_width: int = Field(default=120, ge=10, le=400)
    ascii_charset: str = Field(default=" .:-=+*#%@", min_length=2, max_length=64)
    theme_id: str = Field(default="mono")
    invert: bool = False
    brightness: float = Field(default=1.0, ge=0.1, le=3.0)
    contrast: float = Field(default=1.0, ge=0.1, le=3.0)

    model_config = {"extra": "forbid"}


class RenderConfigPatch(BaseModel):
    """Partial update — all fields optional."""
    flip_horizontal: Optional[bool] = None
    flip_vertical: Optional[bool] = None
    ascii_width: Optional[int] = Field(default=None, ge=10, le=400)
    ascii_charset: Optional[str] = Field(default=None, min_length=2, max_length=64)
    theme_id: Optional[str] = None
    invert: Optional[bool] = None
    brightness: Optional[float] = Field(default=None, ge=0.1, le=3.0)
    contrast: Optional[float] = Field(default=None, ge=0.1, le=3.0)

    model_config = {"extra": "forbid"}


# ── Session ───────────────────────────────────────────────────────────────────

class SessionCreateRequest(BaseModel):
    config: Optional[RenderConfig] = None
    max_fps: int = Field(default=15, ge=1, le=60)
    label: Optional[str] = Field(default=None, max_length=128)


class SessionResponse(BaseModel):
    session_id: uuid.UUID
    label: Optional[str]
    config: RenderConfig
    max_fps: int
    created_at: datetime
    status: str  # "active" | "closed"


class SessionStatsResponse(BaseModel):
    session_id: uuid.UUID
    status: str
    frames_received: int
    frames_processed: int
    frames_dropped: int
    effective_fps: float
    created_at: datetime
    last_frame_at: Optional[datetime]


# ── ASCII Payload (WebSocket push) ────────────────────────────────────────────

class ASCIIPayload(BaseModel):
    frame_id: int
    ascii_text: str
    html_colored_ascii: Optional[str] = None
    fps: float
    processing_ms: float
    width: int
    height: int
    theme_id: str


class WSErrorPayload(BaseModel):
    error: str
    frame_id: Optional[int] = None
    code: int = 400


# ── Snapshot ──────────────────────────────────────────────────────────────────

class SnapshotCreateRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=128)


class SnapshotMetadata(BaseModel):
    snapshot_id: uuid.UUID
    session_id: uuid.UUID
    label: Optional[str]
    theme_id: str
    timestamp: datetime
    retrieval_url: str
    ascii_width: int
    ascii_height: int


class SnapshotDetail(SnapshotMetadata):
    ascii_text: str
    html_colored_ascii: Optional[str] = None


class SnapshotListResponse(BaseModel):
    snapshots: list[SnapshotMetadata]
    total: int


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded" | "unavailable"
    checks: dict[str, str] = {}
    uptime_seconds: float


# ── Auth ──────────────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int