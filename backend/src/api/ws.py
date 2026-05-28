"""
ws.py — WebSocket stream handler

Flow per connection:
  1. Validate JWT token (HTTP upgrade handshake)
  2. Look up session from path param
  3. Accept connection, register in metrics
  4. Receive frames in a loop:
     a. FPS gate — drop if too fast
     b. Size check — reject oversized payloads
     c. Enqueue frame (backpressure via maxsize=2 queue)
     d. Worker task processes: decode → render → theme → push result
  5. On disconnect: drain queue, log summary, update metrics
"""
from __future__ import annotations

import asyncio
import io
import time
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, Depends
from fastapi import status as http_status

from src.api.auth import verify_ws_token
from src.config import get_settings, Settings
from src.models.schemas import ASCIIPayload, WSErrorPayload
from src.observability import metrics
from src.services.ascii_renderer import render_frame
from src.services.session_manager import get_session_manager, SessionState
from src.services.theme_service import apply_theme

log = structlog.get_logger(__name__)
router = APIRouter()


async def _process_frame(
    raw: bytes,
    state: SessionState,
    frame_id: int,
    enqueued_at: float,
) -> Optional[ASCIIPayload]:
    """Run the full render pipeline inside the session semaphore."""
    async with state.semaphore:
        queue_wait_ms = (time.monotonic() - enqueued_at) * 1000
        metrics.frame_queue_wait_ms.observe(queue_wait_ms)

        try:
            result = render_frame(raw, state.config)
        except ValueError as e:
            log.warning("frame.decode_error", session_id=str(state.session_id),
                        frame_id=frame_id, error=str(e))
            metrics.frames_dropped.labels(
                session_id=str(state.session_id), reason="decode_error"
            ).inc()
            return None

        ascii_text = result["ascii_text"]
        source_image = result["source_image"]
        processing_ms = result["processing_ms"]

        # Theme
        html_colored = apply_theme(ascii_text, state.config.theme_id, source_image)

        # Update session state
        state.latest_ascii = ascii_text
        state.latest_html = html_colored
        state.latest_frame = raw
        state.frames_processed += 1
        state.last_frame_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        )

        ts = time.monotonic()
        fps = state.record_fps(ts)

        metrics.frames_processed.labels(session_id=str(state.session_id)).inc()
        metrics.frame_processing_ms.observe(processing_ms)

        return ASCIIPayload(
            frame_id=frame_id,
            ascii_text=ascii_text,
            html_colored_ascii=html_colored,
            fps=round(fps, 2),
            processing_ms=processing_ms,
            width=result["width"],
            height=result["height"],
            theme_id=state.config.theme_id,
        )


async def _frame_worker(
    websocket: WebSocket,
    state: SessionState,
):
    """
    Consumer: pulls frames off the queue, processes them, pushes results back.
    Runs as a background task for the duration of the connection.
    """
    while True:
        item = await state.frame_queue.get()
        if item is None:  # Sentinel — shut down
            state.frame_queue.task_done()
            break

        raw, frame_id, enqueued_at = item
        payload = await _process_frame(raw, state, frame_id, enqueued_at)

        if payload is not None:
            try:
                await websocket.send_text(payload.model_dump_json())
            except Exception:
                # Client disconnected mid-send — worker will exit on next sentinel
                pass

        state.frame_queue.task_done()


@router.websocket("/ws/stream/{session_id}")
async def ws_stream(
    websocket: WebSocket,
    session_id: uuid.UUID,
    token: Optional[str] = Query(default=None),
    settings: Settings = Depends(get_settings),
):
    # ── Auth (HTTP upgrade phase) ─────────────────────────────────────────────
    # In dev mode (jwt_secret == default) we skip auth for convenience.
    # In production, remove this bypass.
    if settings.jwt_secret != "change-me-in-production-please" or token:
        try:
            await verify_ws_token(token=token, settings=settings)
        except Exception:
            await websocket.close(code=http_status.WS_1008_POLICY_VIOLATION)
            return

    # ── Session lookup ────────────────────────────────────────────────────────
    manager = get_session_manager()
    state = await manager.get(session_id)
    if state is None or state.status == "closed":
        await websocket.close(code=http_status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    metrics.active_ws_connections.inc()
    metrics.active_sessions.set(manager.active_count())

    log.info("ws.connected", session_id=str(session_id))

    frame_id = 0
    last_frame_ts: float = 0.0
    min_interval = 1.0 / state.max_fps

    # Start background worker
    worker_task = asyncio.create_task(
        _frame_worker(websocket, state),
        name=f"worker-{session_id}",
    )

    try:
        while True:
            # Receive raw bytes or text (base64)
            try:
                message = await asyncio.wait_for(
                    websocket.receive(), timeout=30.0
                )
            except asyncio.TimeoutError:
                # Ping to keep alive
                await websocket.send_text('{"ping":true}')
                continue

            if message["type"] == "websocket.disconnect":
                break

            raw: Optional[bytes] = None
            if "bytes" in message and message["bytes"]:
                raw = message["bytes"]
            elif "text" in message and message["text"]:
                raw = message["text"].encode()

            if raw is None:
                continue

            frame_id += 1
            state.frames_received += 1
            metrics.frames_received.labels(session_id=str(session_id)).inc()
            metrics.ws_message_size_bytes.observe(len(raw))

            # ── FPS gate ──────────────────────────────────────────────────────
            now = time.monotonic()
            if (now - last_frame_ts) < min_interval:
                state.frames_dropped += 1
                metrics.frames_dropped.labels(
                    session_id=str(session_id), reason="fps_limit"
                ).inc()
                log.debug("frame.dropped.fps", session_id=str(session_id), frame_id=frame_id)
                continue
            last_frame_ts = now

            # ── Size check ────────────────────────────────────────────────────
            if len(raw) > settings.max_frame_bytes:
                err = WSErrorPayload(
                    error=f"Frame too large: {len(raw)} bytes (max {settings.max_frame_bytes})",
                    frame_id=frame_id,
                    code=413,
                )
                await websocket.send_text(err.model_dump_json())
                continue

            # ── Enqueue (backpressure) ────────────────────────────────────────
            try:
                state.frame_queue.put_nowait((raw, frame_id, time.monotonic()))
            except asyncio.QueueFull:
                state.frames_dropped += 1
                metrics.frames_dropped.labels(
                    session_id=str(session_id), reason="queue_full"
                ).inc()
                log.debug("frame.dropped.queue_full", session_id=str(session_id), frame_id=frame_id)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.exception("ws.error", session_id=str(session_id), error=str(e))
        metrics.ws_errors.labels(error_type=type(e).__name__).inc()
    finally:
        # Send sentinel to stop worker
        await state.frame_queue.put(None)
        await worker_task

        metrics.active_ws_connections.dec()
        metrics.active_sessions.set(manager.active_count())

        log.info(
            "ws.disconnected",
            session_id=str(session_id),
            frames_received=state.frames_received,
            frames_processed=state.frames_processed,
            frames_dropped=state.frames_dropped,
        )