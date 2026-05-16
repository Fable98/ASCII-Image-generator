"""
metrics.py — Prometheus counters and histograms
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry

# Use default registry
REGISTRY = CollectorRegistry(auto_describe=True)

# ── Counters ──────────────────────────────────────────────────────────────────

frames_received = Counter(
    "ascii_frames_received_total",
    "Total frames received from clients",
    ["session_id"],
)

frames_processed = Counter(
    "ascii_frames_processed_total",
    "Total frames successfully converted to ASCII",
    ["session_id"],
)

frames_dropped = Counter(
    "ascii_frames_dropped_total",
    "Total frames dropped due to backpressure or rate limits",
    ["session_id", "reason"],  # reason: queue_full | fps_limit | decode_error
)

sessions_created = Counter(
    "ascii_sessions_created_total",
    "Total sessions created",
)

sessions_closed = Counter(
    "ascii_sessions_closed_total",
    "Total sessions closed",
    ["reason"],  # reason: client_disconnect | ttl_evict | error
)

snapshots_saved = Counter(
    "ascii_snapshots_saved_total",
    "Total snapshots persisted",
)

ws_errors = Counter(
    "ascii_ws_errors_total",
    "WebSocket errors by type",
    ["error_type"],
)

# ── Gauges ────────────────────────────────────────────────────────────────────

active_sessions = Gauge(
    "ascii_active_sessions",
    "Number of currently active sessions",
)

active_ws_connections = Gauge(
    "ascii_active_ws_connections",
    "Number of open WebSocket connections",
)

# ── Histograms ────────────────────────────────────────────────────────────────

frame_processing_ms = Histogram(
    "ascii_frame_processing_ms",
    "Per-frame end-to-end processing latency in milliseconds",
    buckets=[1, 5, 10, 20, 50, 100, 200, 500, 1000],
)

frame_queue_wait_ms = Histogram(
    "ascii_frame_queue_wait_ms",
    "Time a frame spent waiting in the queue before processing",
    buckets=[0.5, 1, 2, 5, 10, 25, 50, 100],
)

ws_message_size_bytes = Histogram(
    "ascii_ws_message_size_bytes",
    "Size of incoming WebSocket messages",
    buckets=[1024, 4096, 16384, 65536, 262144, 524288, 1048576, 2097152],
)