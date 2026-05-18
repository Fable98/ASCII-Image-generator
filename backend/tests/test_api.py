"""
test_api.py — Integration tests for session + config + snapshot REST API
"""
import io
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from PIL import Image

from src.main import app


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="module")
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def make_jpeg(color=(100, 150, 200), size=(64, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="JPEG")
    return buf.getvalue()


# ── Health ────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_liveness(client):
    r = await client.get("/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.anyio
async def test_readiness(client):
    r = await client.get("/health/ready")
    assert r.status_code in (200, 503)
    assert "status" in r.json()


# ── Sessions ──────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_create_session_defaults(client):
    r = await client.post("/sessions", json={})
    assert r.status_code == 201
    data = r.json()
    assert "session_id" in data
    assert data["status"] == "active"
    assert data["config"]["ascii_width"] == 120


@pytest.mark.anyio
async def test_create_session_with_config(client):
    r = await client.post("/sessions", json={
        "config": {"ascii_width": 60, "theme_id": "green", "flip_horizontal": True},
        "max_fps": 10,
        "label": "test-session",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["config"]["ascii_width"] == 60
    assert data["config"]["theme_id"] == "green"
    assert data["config"]["flip_horizontal"] is True
    assert data["label"] == "test-session"
    assert data["max_fps"] == 10


@pytest.mark.anyio
async def test_get_session_stats(client):
    r = await client.post("/sessions", json={})
    session_id = r.json()["session_id"]

    r2 = await client.get(f"/sessions/{session_id}")
    assert r2.status_code == 200
    data = r2.json()
    assert data["session_id"] == session_id
    assert data["frames_received"] == 0
    assert data["frames_processed"] == 0


@pytest.mark.anyio
async def test_get_nonexistent_session_404(client):
    r = await client.get("/sessions/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


# ── Config PATCH ──────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_patch_config(client):
    r = await client.post("/sessions", json={})
    session_id = r.json()["session_id"]

    r2 = await client.patch(f"/sessions/{session_id}/config", json={
        "ascii_width": 80,
        "theme_id": "amber",
        "invert": True,
    })
    assert r2.status_code == 200
    data = r2.json()
    assert data["ascii_width"] == 80
    assert data["theme_id"] == "amber"
    assert data["invert"] is True
    # Unchanged fields preserved
    assert "flip_horizontal" in data


@pytest.mark.anyio
async def test_patch_config_invalid_field(client):
    r = await client.post("/sessions", json={})
    session_id = r.json()["session_id"]

    r2 = await client.patch(f"/sessions/{session_id}/config", json={
        "nonexistent_field": "boom"
    })
    assert r2.status_code == 422


# ── Stop session ──────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_stop_session(client):
    r = await client.post("/sessions", json={})
    session_id = r.json()["session_id"]

    r2 = await client.post(f"/sessions/{session_id}/stop")
    assert r2.status_code == 204

    r3 = await client.get(f"/sessions/{session_id}")
    assert r3.status_code == 404


# ── Snapshot (no frames yet → 409) ───────────────────────────────────────────

@pytest.mark.anyio
async def test_snapshot_before_frames_is_conflict(client):
    r = await client.post("/sessions", json={})
    session_id = r.json()["session_id"]

    r2 = await client.post(f"/sessions/{session_id}/snapshot", json={})
    assert r2.status_code == 409


@pytest.mark.anyio
async def test_list_snapshots_empty(client):
    r = await client.post("/sessions", json={})
    session_id = r.json()["session_id"]

    r2 = await client.get(f"/sessions/{session_id}/snapshots")
    assert r2.status_code == 200
    assert r2.json()["total"] == 0
    assert r2.json()["snapshots"] == []