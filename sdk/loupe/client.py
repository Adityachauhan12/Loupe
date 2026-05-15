from __future__ import annotations

import logging

import httpx

from loupe.models import TracePayload

logger = logging.getLogger("loupe")

_MAX_RETRIES = 3
_TIMEOUT = 10.0  # seconds


class LoupeClient:
    def __init__(self, api_key: str, host: str) -> None:
        self._headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
        self._host = host.rstrip("/")

    def flush(self, trace: TracePayload) -> None:
        """Send trace to the server synchronously with simple retry."""
        url = f"{self._host}/v1/traces"
        body = trace.model_dump_json()

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = httpx.post(
                    url,
                    content=body,
                    headers=self._headers,
                    timeout=_TIMEOUT,
                )
                if resp.status_code in (200, 201):
                    return
                if resp.status_code < 500:
                    # 4xx — retrying won't help
                    logger.warning("loupe: server rejected trace (%s): %s", resp.status_code, resp.text)
                    return
                # 5xx — retry
                logger.warning("loupe: server error (attempt %d/%d): %s", attempt, _MAX_RETRIES, resp.status_code)
            except httpx.TransportError as exc:
                logger.warning("loupe: network error (attempt %d/%d): %s", attempt, _MAX_RETRIES, exc)

        logger.error("loupe: failed to deliver trace %s after %d attempts", trace.id, _MAX_RETRIES)
