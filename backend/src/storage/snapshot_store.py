"""
snapshot_store.py — Snapshot persistence (local filesystem + S3-ready interface)
"""
from __future__ import annotations

import json
import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

import aiofiles
import structlog

log = structlog.get_logger(__name__)


class SnapshotStore(ABC):
    @abstractmethod
    async def save(
        self,
        session_id: uuid.UUID,
        snapshot_id: uuid.UUID,
        ascii_text: str,
        html_colored_ascii: Optional[str],
        original_frame: bytes,
        theme_id: str,
        label: Optional[str],
        ascii_width: int,
        ascii_height: int,
    ) -> dict:
        ...

    @abstractmethod
    async def get(self, snapshot_id: uuid.UUID) -> Optional[dict]:
        ...

    @abstractmethod
    async def list_for_session(self, session_id: uuid.UUID) -> list[dict]:
        ...


class LocalSnapshotStore(SnapshotStore):
    """
    Stores snapshots on the local filesystem under base_dir.
    Layout:
        {base_dir}/{session_id}/{snapshot_id}/
            meta.json        — metadata + ascii_text
            frame.jpg        — original frame bytes
            colored.html     — html_colored_ascii (if present)
    """

    def __init__(self, base_dir: str = "/tmp/ascii_snapshots"):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def _snapshot_dir(self, session_id: uuid.UUID, snapshot_id: uuid.UUID) -> str:
        return os.path.join(self.base_dir, str(session_id), str(snapshot_id))

    def _retrieval_url(self, session_id: uuid.UUID, snapshot_id: uuid.UUID) -> str:
        return f"/snapshots/{snapshot_id}"

    async def save(
        self,
        session_id: uuid.UUID,
        snapshot_id: uuid.UUID,
        ascii_text: str,
        html_colored_ascii: Optional[str],
        original_frame: bytes,
        theme_id: str,
        label: Optional[str],
        ascii_width: int,
        ascii_height: int,
    ) -> dict:
        snap_dir = self._snapshot_dir(session_id, snapshot_id)
        os.makedirs(snap_dir, exist_ok=True)
        tmp_prefix = os.path.join(snap_dir, ".tmp_")

        timestamp = datetime.now(timezone.utc).isoformat()
        meta = {
            "snapshot_id": str(snapshot_id),
            "session_id": str(session_id),
            "label": label,
            "theme_id": theme_id,
            "timestamp": timestamp,
            "retrieval_url": self._retrieval_url(session_id, snapshot_id),
            "ascii_width": ascii_width,
            "ascii_height": ascii_height,
            "ascii_text": ascii_text,
            "has_html": html_colored_ascii is not None,
        }

        # Atomic write: write to tmp then rename
        meta_path = os.path.join(snap_dir, "meta.json")
        tmp_meta = tmp_prefix + "meta.json"
        async with aiofiles.open(tmp_meta, "w") as f:
            await f.write(json.dumps(meta, indent=2))
        os.rename(tmp_meta, meta_path)

        # Frame
        frame_path = os.path.join(snap_dir, "frame.jpg")
        tmp_frame = tmp_prefix + "frame.jpg"
        async with aiofiles.open(tmp_frame, "wb") as f:
            await f.write(original_frame)
        os.rename(tmp_frame, frame_path)

        # HTML (optional)
        if html_colored_ascii:
            html_path = os.path.join(snap_dir, "colored.html")
            tmp_html = tmp_prefix + "colored.html"
            async with aiofiles.open(tmp_html, "w") as f:
                await f.write(html_colored_ascii)
            os.rename(tmp_html, html_path)

        log.info(
            "snapshot.saved",
            snapshot_id=str(snapshot_id),
            session_id=str(session_id),
            path=snap_dir,
        )
        return meta

    async def get(self, snapshot_id: uuid.UUID) -> Optional[dict]:
        # Search across all sessions
        if not os.path.isdir(self.base_dir):
            return None
        for session_dir in os.listdir(self.base_dir):
            meta_path = os.path.join(
                self.base_dir, session_dir, str(snapshot_id), "meta.json"
            )
            if os.path.isfile(meta_path):
                async with aiofiles.open(meta_path) as f:
                    meta = json.loads(await f.read())
                # Load html if present
                html_path = os.path.join(
                    self.base_dir, session_dir, str(snapshot_id), "colored.html"
                )
                if os.path.isfile(html_path):
                    async with aiofiles.open(html_path) as f:
                        meta["html_colored_ascii"] = await f.read()
                return meta
        return None

    async def list_for_session(self, session_id: uuid.UUID) -> list[dict]:
        session_dir = os.path.join(self.base_dir, str(session_id))
        if not os.path.isdir(session_dir):
            return []

        results = []
        for snap_id_str in os.listdir(session_dir):
            meta_path = os.path.join(session_dir, snap_id_str, "meta.json")
            if os.path.isfile(meta_path):
                async with aiofiles.open(meta_path) as f:
                    results.append(json.loads(await f.read()))

        results.sort(key=lambda m: m["timestamp"], reverse=True)
        return results


class S3SnapshotStore(SnapshotStore):
    """
    S3-backed snapshot store. Swap in by setting SNAPSHOT_BACKEND=s3.
    Requires S3_BUCKET and AWS credentials in environment.
    """

    def __init__(self, bucket: str, region: str = "us-east-1"):
        import boto3
        self.bucket = bucket
        self.s3 = boto3.client("s3", region_name=region)

    def _key(self, session_id: uuid.UUID, snapshot_id: uuid.UUID, file: str) -> str:
        return f"snapshots/{session_id}/{snapshot_id}/{file}"

    def _presigned_url(self, session_id: uuid.UUID, snapshot_id: uuid.UUID) -> str:
        key = self._key(session_id, snapshot_id, "frame.jpg")
        return self.s3.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=3600
        )

    async def save(self, session_id, snapshot_id, ascii_text,
                   html_colored_ascii, original_frame, theme_id,
                   label, ascii_width, ascii_height) -> dict:
        import asyncio, functools
        loop = asyncio.get_event_loop()

        timestamp = datetime.now(timezone.utc).isoformat()
        meta = {
            "snapshot_id": str(snapshot_id),
            "session_id": str(session_id),
            "label": label,
            "theme_id": theme_id,
            "timestamp": timestamp,
            "retrieval_url": self._presigned_url(session_id, snapshot_id),
            "ascii_width": ascii_width,
            "ascii_height": ascii_height,
            "ascii_text": ascii_text,
            "has_html": html_colored_ascii is not None,
        }

        put = functools.partial
        await loop.run_in_executor(None, functools.partial(
            self.s3.put_object,
            Bucket=self.bucket,
            Key=self._key(session_id, snapshot_id, "meta.json"),
            Body=json.dumps(meta).encode(),
            ContentType="application/json",
        ))
        await loop.run_in_executor(None, functools.partial(
            self.s3.put_object,
            Bucket=self.bucket,
            Key=self._key(session_id, snapshot_id, "frame.jpg"),
            Body=original_frame,
            ContentType="image/jpeg",
        ))
        if html_colored_ascii:
            await loop.run_in_executor(None, functools.partial(
                self.s3.put_object,
                Bucket=self.bucket,
                Key=self._key(session_id, snapshot_id, "colored.html"),
                Body=html_colored_ascii.encode(),
                ContentType="text/html",
            ))
        return meta

    async def get(self, snapshot_id: uuid.UUID) -> Optional[dict]:
        # Requires knowing session_id — in production, index in Redis
        raise NotImplementedError("Use list_for_session or pass session_id")

    async def list_for_session(self, session_id: uuid.UUID) -> list[dict]:
        import asyncio, functools, json as _json
        loop = asyncio.get_event_loop()
        prefix = f"snapshots/{session_id}/"
        resp = await loop.run_in_executor(None, functools.partial(
            self.s3.list_objects_v2, Bucket=self.bucket, Prefix=prefix, Delimiter="/"
        ))
        results = []
        for obj in resp.get("CommonPrefixes", []):
            snap_prefix = obj["Prefix"]
            meta_key = snap_prefix + "meta.json"
            try:
                body = await loop.run_in_executor(None, functools.partial(
                    self.s3.get_object, Bucket=self.bucket, Key=meta_key
                ))
                results.append(_json.loads(body["Body"].read()))
            except Exception:
                pass
        results.sort(key=lambda m: m["timestamp"], reverse=True)
        return results


def get_snapshot_store(backend: str = "local", **kwargs) -> SnapshotStore:
    if backend == "s3":
        return S3SnapshotStore(
            bucket=kwargs.get("bucket", ""),
            region=kwargs.get("region", "us-east-1"),
        )
    return LocalSnapshotStore(base_dir=kwargs.get("base_dir", "/tmp/ascii_snapshots"))