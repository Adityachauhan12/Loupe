import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, get_db
from app.models import ApiKey

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

_LAST_USED_UPDATE_INTERVAL = timedelta(minutes=5)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_key() -> tuple[str, str]:
    """Return (raw_key, key_hash). The raw key is shown to the user once."""
    raw = "lp_" + secrets.token_urlsafe(32)
    return raw, hash_key(raw)


async def _touch_last_used(api_key_id: object, last_used_at: datetime | None) -> None:
    """Update last_used_at in its own session, debounced to once per 5 minutes."""
    now = datetime.now(timezone.utc)
    if last_used_at is not None:
        # Make last_used_at tz-aware for comparison if it isn't already.
        if last_used_at.tzinfo is None:
            last_used_at = last_used_at.replace(tzinfo=timezone.utc)
        if now - last_used_at < _LAST_USED_UPDATE_INTERVAL:
            return

    async with SessionLocal() as session:
        await session.execute(
            update(ApiKey).where(ApiKey.id == api_key_id).values(last_used_at=now)
        )
        await session.commit()


async def require_api_key(
    x_api_key: str | None = Depends(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    key_hash = hash_key(x_api_key)
    result = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    # Fire-and-forget: update last_used_at in its own session so the route's
    # transaction is not affected. Debounced to avoid a hot-row write per request.
    await _touch_last_used(api_key.id, api_key.last_used_at)

    return api_key
