"""
session_manager.py — In-memory session store (Redis-ready interface)
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

from src.models.schemas import RenderConfig, RenderConfigPatch

log = structlog.get_logger(__name__)


class SessionState:
    def __init__(
        self,
        session_id: uuid.UUID,
        config: RenderConfig,
        max_fps: int,
        label: Optional[str] = None,
    ):
        self.session_id = session_id
        self.label = label
        self.config = config
        self.max_fps = max_fps
        self.status = "active"
        self.created_at = datetime.now(timezone.utc)
        self.last_frame_at: Optional[datetime] = None

        # Stats (atomic-ish via asyncio single-thread)
        self.frames_received: int = 0
        self.frames_processed: int = 0
        self.frames_dropped: int = 0

        # Latest ASCII output for snapshot
        self.latest_ascii: Optional[str] = None
        self.latest_html: Optional[str] = None

        # Backpressure
        self.frame_queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        self.semaphore: asyncio.Semaphore = asyncio.Semaphore(4)

        # FPS tracking
        self._fps_window: list[float] = []

    def update_config(self, patch: RenderConfigPatch) -> RenderConfig:
        data = self.config.model_dump()
        for field, value in patch.model_dump(exclude_none=True).items():
            data[field] = value
        self.config = RenderConfig(**data)
        return self.config

    def record_fps(self, ts: float) -> float:
        self._fps_window.append(ts)
        cutoff = ts - 3.0
        self._fps_window = [t for t in self._fps_window if t > cutoff]
        return len(self._fps_window) / 3.0 if len(self._fps_window) > 1 else 0.0

    @property
    def effective_fps(self) -> float:
        import time
        ts = time.monotonic()
        cutoff = ts - 3.0
        self._fps_window = [t for t in self._fps_window if t > cutoff]
        return len(self._fps_window) / 3.0 if len(self._fps_window) > 1 else 0.0

    def close(self):
        self.status = "closed"


class SessionManager:
    """
    In-memory session store. Interface is identical to a Redis-backed version —
    swap the implementation in Phase 4 without touching callers.
    """

    def __init__(self):
        self._sessions: dict[uuid.UUID, SessionState] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self, ttl_seconds: int = 600, interval: int = 60):
        self._ttl = ttl_seconds
        self._cleanup_task = asyncio.create_task(
            self._cleanup_loop(interval), name="session-gc"
        )
        log.info("session_manager.started", ttl=ttl_seconds, interval=interval)

    async def stop(self):
        if self._cleanup_task:
            self._cleanup_task.cancel()
        log.info("session_manager.stopped", active=len(self._sessions))

    async def create(
        self,
        config: Optional[RenderConfig] = None,
        max_fps: int = 15,
        label: Optional[str] = None,
    ) -> SessionState:
        session_id = uuid.uuid4()
        state = SessionState(
            session_id=session_id,
            config=config or RenderConfig(),
            max_fps=max_fps,
            label=label,
        )
        async with self._lock:
            self._sessions[session_id] = state
        log.info("session.created", session_id=str(session_id), label=label)
        return state

    async def get(self, session_id: uuid.UUID) -> Optional[SessionState]:
        return self._sessions.get(session_id)

    async def require(self, session_id: uuid.UUID) -> SessionState:
        state = await self.get(session_id)
        if state is None or state.status == "closed":
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Session not found or closed")
        return state

    async def close_session(self, session_id: uuid.UUID):
        state = self._sessions.get(session_id)
        if state:
            state.close()
            log.info(
                "session.closed",
                session_id=str(session_id),
                processed=state.frames_processed,
                dropped=state.frames_dropped,
            )

    async def _cleanup_loop(self, interval: int):
        while True:
            await asyncio.sleep(interval)
            await self._evict_idle()

    async def _evict_idle(self):
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        to_evict = []
        async with self._lock:
            for sid, state in self._sessions.items():
                last = state.last_frame_at or state.created_at
                if (now - last).total_seconds() > self._ttl:
                    to_evict.append(sid)
            for sid in to_evict:
                self._sessions[sid].close()
                del self._sessions[sid]
        if to_evict:
            log.info("session.evicted", count=len(to_evict))

    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.status == "active")


# Singleton
_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager