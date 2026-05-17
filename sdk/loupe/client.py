from __future__ import annotations

import asyncio
import atexit
import logging
import threading
from typing import Any

import httpx

from loupe.models import TracePayload

logger = logging.getLogger("loupe")

_MAX_RETRIES = 3
_TIMEOUT = 10.0       # seconds per HTTP request
_BATCH_SIZE = 10      # max traces sent concurrently per drain cycle
_BACKOFF_BASE = 1.0   # seconds; doubles each retry (1s, 2s, 4s)


class LoupeClient:
    """
    Non-blocking trace client.

    Traces are queued in memory and sent in the background by a worker thread
    that runs its own asyncio event loop. Up to _BATCH_SIZE traces are sent
    concurrently per cycle. Failed sends are retried with exponential backoff.
    On process exit, atexit drains the queue before the thread stops.
    """

    def __init__(self, api_key: str, host: str) -> None:
        self._url = host.rstrip("/") + "/v1/traces"
        self._headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        }

        # Shared between threads; set before _ready fires.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[TracePayload | None] | None = None

        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="loupe-worker"
        )
        self._thread.start()
        self._ready.wait(timeout=5.0)  # wait for loop + queue to exist

        atexit.register(self._shutdown)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, trace: TracePayload) -> None:
        """Non-blocking: hand the trace to the background worker."""
        if self._loop is not None and self._loop.is_running() and self._queue is not None:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, trace)

    # ------------------------------------------------------------------
    # Background thread
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._queue = asyncio.Queue()
        self._ready.set()
        loop.run_until_complete(self._worker())

    async def _worker(self) -> None:
        async with httpx.AsyncClient(headers=self._headers, timeout=_TIMEOUT) as http:
            while True:
                # Block until at least one trace (or shutdown signal) arrives.
                item = await self._queue.get()  # type: ignore[union-attr]

                if item is None:
                    return  # clean shutdown; all prior items already processed

                # Collect additional traces that are immediately available.
                batch: list[TracePayload] = [item]
                while len(batch) < _BATCH_SIZE:
                    try:
                        next_item = self._queue.get_nowait()  # type: ignore[union-attr]
                    except asyncio.QueueEmpty:
                        break
                    if next_item is None:
                        # Shutdown signal found mid-batch: send current batch then exit.
                        await self._flush_batch(http, batch)
                        return
                    batch.append(next_item)

                await self._flush_batch(http, batch)

    async def _flush_batch(
        self, http: httpx.AsyncClient, batch: list[TracePayload]
    ) -> None:
        await asyncio.gather(*[self._send_with_retry(http, t) for t in batch])

    async def _send_with_retry(
        self, http: httpx.AsyncClient, trace: TracePayload
    ) -> None:
        body = trace.model_dump_json()

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = await http.post(self._url, content=body)
                if resp.status_code in (200, 201):
                    return
                if resp.status_code < 500:
                    # 4xx — retrying won't help
                    logger.warning(
                        "loupe: server rejected trace %s (%s): %s",
                        trace.id, resp.status_code, resp.text,
                    )
                    return
                logger.warning(
                    "loupe: server error for trace %s (attempt %d/%d): %s",
                    trace.id, attempt, _MAX_RETRIES, resp.status_code,
                )
            except httpx.TransportError as exc:
                logger.warning(
                    "loupe: network error for trace %s (attempt %d/%d): %s",
                    trace.id, attempt, _MAX_RETRIES, exc,
                )

            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))

        logger.error(
            "loupe: failed to deliver trace %s after %d attempts", trace.id, _MAX_RETRIES
        )

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _shutdown(self) -> None:
        """atexit hook — drain the queue then stop the worker."""
        if (
            self._loop is None
            or not self._loop.is_running()
            or self._queue is None
        ):
            return
        # Poison pill: worker processes everything ahead of this, then exits.
        self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
        self._thread.join(timeout=15.0)
