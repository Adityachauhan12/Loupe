from __future__ import annotations

import atexit
import logging
import queue
import threading
import time

import httpx

from loupe.models import TracePayload

logger = logging.getLogger("loupe")

_MAX_RETRIES = 3
_TIMEOUT = 10.0       # seconds per HTTP request
_BACKOFF_BASE = 1.0   # seconds; doubles each retry (1s, 2s, 4s)
_DRAIN_TIMEOUT = 15.0 # max seconds to wait at shutdown for the queue to drain


class LoupeClient:
    """
    Non-blocking trace client.

    Traces are queued in memory and sent in the background by a single
    worker thread using a synchronous httpx.Client. On process exit, an
    atexit hook sends a poison pill and joins the worker so any in-flight
    traces finish before the interpreter shuts down.

    Why sync, not async? An earlier version used httpx.AsyncClient on its
    own asyncio loop. When a trace was enqueued just before script exit,
    the worker would race against Python's atexit phase: httpx-async's
    lazy initialisation called atexit.register() during shutdown, which
    Python refuses with RuntimeError. Sync httpx.Client does all of its
    setup eagerly in the constructor, avoiding that race entirely.
    """

    def __init__(self, api_key: str, host: str) -> None:
        self._url = host.rstrip("/") + "/v1/traces"
        self._headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        }
        self._queue: queue.Queue[TracePayload | None] = queue.Queue()
        self._shutdown_event = threading.Event()

        # Constructed eagerly: any lazy imports / resource setup happens
        # now, not during the atexit phase. See class docstring.
        self._http = httpx.Client(headers=self._headers, timeout=_TIMEOUT)

        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="loupe-worker"
        )
        self._thread.start()

        atexit.register(self._shutdown)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, trace: TracePayload) -> None:
        """Non-blocking: hand the trace to the background worker."""
        if self._shutdown_event.is_set():
            return
        self._queue.put(trace)

    def fetch_trace(self, trace_id: str) -> dict:
        """Blocking GET of a trace (with spans) — used by replay to load the
        original run before re-executing it."""
        resp = self._http.get(f"{self._url}/{trace_id}")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Background thread
    # ------------------------------------------------------------------

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return  # poison pill — clean shutdown
                self._send_with_retry(item)
            finally:
                self._queue.task_done()

    def _send_with_retry(self, trace: TracePayload) -> None:
        body = trace.model_dump_json()

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = self._http.post(self._url, content=body)
                if resp.status_code in (200, 201):
                    return
                if resp.status_code < 500:
                    # 4xx — retrying won't help
                    logger.warning(
                        "loupe: server rejected trace %s (%s): %s",
                        trace.id, resp.status_code, resp.text[:200],
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
            except Exception as exc:
                # Unexpected error (serialization, SSL config, etc.) — log and abort.
                logger.error("loupe: unexpected error delivering trace %s: %s", trace.id, exc)
                return

            if attempt < _MAX_RETRIES:
                time.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))

        logger.error(
            "loupe: failed to deliver trace %s after %d attempts", trace.id, _MAX_RETRIES
        )

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _shutdown(self) -> None:
        """atexit hook — block enqueues, drain the queue, stop the worker."""
        if self._shutdown_event.is_set():
            return
        self._shutdown_event.set()

        # Wait for currently-queued traces to flush, then poison-pill the worker.
        try:
            self._queue.join()
        except Exception:
            pass

        self._queue.put(None)
        self._thread.join(timeout=_DRAIN_TIMEOUT)

        try:
            self._http.close()
        except Exception:
            pass
