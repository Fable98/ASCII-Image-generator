"""
auth.py — JWT token creation and FastAPI dependency
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from src.config import Settings, get_settings

log = structlog.get_logger(__name__)

security = HTTPBearer(auto_error=False)


def create_access_token(
    subject: str,
    settings: Settings,
    expires_delta: Optional[timedelta] = None,
) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    )
    payload = {"sub": subject, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_token(token: str, settings: Settings) -> dict:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def verify_jwt(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    settings: Settings = Depends(get_settings),
) -> dict:
    """REST dependency — extracts and validates Bearer JWT."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _decode_token(credentials.credentials, settings)


async def verify_ws_token(
    token: Optional[str] = Query(default=None),
    settings: Settings = Depends(get_settings),
) -> dict:
    """
    WebSocket auth — client passes ?token=<jwt> as query param.
    Called during the HTTP upgrade handshake.
    """
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="WebSocket auth token missing (?token=…)",
        )
    return _decode_token(token, settings)