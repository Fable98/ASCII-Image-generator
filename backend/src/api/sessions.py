"""
sessions.py — REST API endpoints for sessions, auth, and snapshots
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status

from src.api.auth import create_access_token
from src.config import Settings, get_settings
from src.models.schemas import (
    RenderConfig,
    RenderConfigPatch,
    SessionCreateRequest,
    SessionResponse,
    SessionStatsResponse,
    SnapshotCreateRequest,
    SnapshotDetail,
    SnapshotListResponse,
    SnapshotMetadata,
    TokenResponse,
)
from src.services.session_manager import get_session_manager
from src.storage.snapshot_store import get_snapshot_store

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])
auth_router = APIRouter(prefix="/auth", tags=["auth"])
snapshots_router = APIRouter(tags=["snapshots"])


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: Optional[SessionCreateRequest] = None,
    settings: Settings = Depends(get_settings),
):
    payload = payload or SessionCreateRequest()
    manager = get_session_manager()
    session = await manager.create(
        config=payload.config,
        max_fps=payload.max_fps,
        label=payload.label,
    )
    return SessionResponse(
        session_id=session.session_id,
        label=session.label,
        config=session.config,
        max_fps=session.max_fps,
        created_at=session.created_at,
        status=session.status,
    )


@router.get("/{session_id}", response_model=SessionStatsResponse)
async def get_session_stats(
    session_id: uuid.UUID,
):
    manager = get_session_manager()
    session = await manager.require(session_id)
    return SessionStatsResponse(
        session_id=session.session_id,
        status=session.status,
        frames_received=session.frames_received,
        frames_processed=session.frames_processed,
        frames_dropped=session.frames_dropped,
        effective_fps=session.effective_fps,
        created_at=session.created_at,
        last_frame_at=session.last_frame_at,
    )


@router.patch("/{session_id}/config", response_model=RenderConfig)
async def patch_session_config(
    session_id: uuid.UUID,
    patch: RenderConfigPatch,
):
    manager = get_session_manager()
    session = await manager.require(session_id)
    return session.update_config(patch)


@router.post("/{session_id}/stop", status_code=status.HTTP_204_NO_CONTENT)
async def stop_session(
    session_id: uuid.UUID,
):
    manager = get_session_manager()
    # Ensure session exists first to throw 404 if not active
    await manager.require(session_id)
    await manager.close_session(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.post("/token", response_model=TokenResponse)
async def login_for_access_token(
    settings: Settings = Depends(get_settings),
):
    access_token = create_access_token(subject="admin", settings=settings)
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.jwt_expire_minutes * 60,
    )


@snapshots_router.post("/sessions/{session_id}/snapshot", response_model=SnapshotDetail, status_code=status.HTTP_201_CREATED)
async def create_snapshot(
    session_id: uuid.UUID,
    payload: Optional[SnapshotCreateRequest] = None,
    settings: Settings = Depends(get_settings),
):
    payload = payload or SnapshotCreateRequest()
    manager = get_session_manager()
    session = await manager.require(session_id)
    
    if session.latest_ascii is None or session.latest_frame is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No frames processed yet",
        )
    
    snapshot_id = uuid.uuid4()
    store = get_snapshot_store(
        backend=settings.snapshot_backend,
        base_dir=settings.snapshot_local_dir,
        bucket=settings.s3_bucket,
        region=settings.s3_region,
    )
    
    # Calculate dimensions from latest ascii text
    lines = session.latest_ascii.split("\n")
    height = len(lines)
    width = len(lines[0]) if height > 0 else 0
    
    meta = await store.save(
        session_id=session_id,
        snapshot_id=snapshot_id,
        ascii_text=session.latest_ascii,
        html_colored_ascii=session.latest_html,
        original_frame=session.latest_frame,
        theme_id=session.config.theme_id,
        label=payload.label,
        ascii_width=width,
        ascii_height=height,
    )
    
    return SnapshotDetail(
        snapshot_id=snapshot_id,
        session_id=session_id,
        label=meta["label"],
        theme_id=meta["theme_id"],
        timestamp=datetime.fromisoformat(meta["timestamp"]),
        retrieval_url=meta["retrieval_url"],
        ascii_width=meta["ascii_width"],
        ascii_height=meta["ascii_height"],
        ascii_text=meta["ascii_text"],
        html_colored_ascii=session.latest_html,
    )


@snapshots_router.get("/sessions/{session_id}/snapshots", response_model=SnapshotListResponse)
async def list_snapshots(
    session_id: uuid.UUID,
    settings: Settings = Depends(get_settings),
):
    manager = get_session_manager()
    await manager.require(session_id)
    
    store = get_snapshot_store(
        backend=settings.snapshot_backend,
        base_dir=settings.snapshot_local_dir,
        bucket=settings.s3_bucket,
        region=settings.s3_region,
    )
    
    snapshots_meta = await store.list_for_session(session_id)
    
    snapshots = [
        SnapshotMetadata(
            snapshot_id=uuid.UUID(meta["snapshot_id"]),
            session_id=uuid.UUID(meta["session_id"]),
            label=meta["label"],
            theme_id=meta["theme_id"],
            timestamp=datetime.fromisoformat(meta["timestamp"]),
            retrieval_url=meta["retrieval_url"],
            ascii_width=meta["ascii_width"],
            ascii_height=meta["ascii_height"],
        )
        for meta in snapshots_meta
    ]
    
    return SnapshotListResponse(
        snapshots=snapshots,
        total=len(snapshots),
    )


@snapshots_router.get("/snapshots/{snapshot_id}", response_model=SnapshotDetail)
async def get_snapshot(
    snapshot_id: uuid.UUID,
    settings: Settings = Depends(get_settings),
):
    store = get_snapshot_store(
        backend=settings.snapshot_backend,
        base_dir=settings.snapshot_local_dir,
        bucket=settings.s3_bucket,
        region=settings.s3_region,
    )
    
    meta = await store.get(snapshot_id)
    if meta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Snapshot not found",
        )
        
    return SnapshotDetail(
        snapshot_id=uuid.UUID(meta["snapshot_id"]),
        session_id=uuid.UUID(meta["session_id"]),
        label=meta["label"],
        theme_id=meta["theme_id"],
        timestamp=datetime.fromisoformat(meta["timestamp"]),
        retrieval_url=meta["retrieval_url"],
        ascii_width=meta["ascii_width"],
        ascii_height=meta["ascii_height"],
        ascii_text=meta["ascii_text"],
        html_colored_ascii=meta.get("html_colored_ascii"),
    )