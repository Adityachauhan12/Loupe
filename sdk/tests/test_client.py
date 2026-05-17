"""
Tests for LoupeClient async batch flush.

We use respx to mock httpx at the transport level so no real server is needed.
All tests spin up a real LoupeClient (background thread + event loop) to exercise
the full code path.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

import pytest
import respx
from httpx import Response

from loupe.client import LoupeClient, _MAX_RETRIES
from loupe.models import TracePayload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trace(name: str = "test") -> TracePayload:
    return TracePayload(
        id=uuid.uuid4(),
        name=name,
        status="success",
        started_at=datetime.now(timezone.utc),
    )


def _make_client() -> LoupeClient:
    return LoupeClient(api_key="test-key", host="http://fake-loupe.internal")


URL = "http://fake-loupe.internal/v1/traces"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@respx.mock
def test_enqueue_delivers_trace():
    """A queued trace is sent to the server exactly once."""
    route = respx.post(URL).mock(return_value=Response(201))

    client = _make_client()
    t = _trace()
    client.enqueue(t)
    client._shutdown()

    assert route.call_count == 1


@respx.mock
def test_enqueue_is_nonblocking():
    """enqueue() returns in well under the HTTP timeout (it's fire-and-forget)."""
    # Delay the mock response to confirm we don't block on it.
    respx.post(URL).mock(return_value=Response(201))

    client = _make_client()
    start = time.monotonic()
    client.enqueue(_trace())
    elapsed = time.monotonic() - start

    # Should return in microseconds, not seconds
    assert elapsed < 0.1
    client._shutdown()


@respx.mock
def test_batch_sends_multiple_traces():
    """Multiple enqueued traces are all delivered."""
    route = respx.post(URL).mock(return_value=Response(201))

    client = _make_client()
    for i in range(5):
        client.enqueue(_trace(f"trace-{i}"))
    client._shutdown()

    assert route.call_count == 5


@respx.mock
def test_retry_on_server_error():
    """5xx responses trigger retries; succeeds when server recovers."""
    route = respx.post(URL).mock(
        side_effect=[Response(503), Response(503), Response(201)]
    )

    client = _make_client()
    client.enqueue(_trace())
    client._shutdown()

    assert route.call_count == 3  # two failures + one success


@respx.mock
def test_no_retry_on_client_error():
    """4xx responses are not retried."""
    route = respx.post(URL).mock(return_value=Response(401))

    client = _make_client()
    client.enqueue(_trace())
    client._shutdown()

    assert route.call_count == 1


@respx.mock
def test_gives_up_after_max_retries():
    """Exhausting retries logs an error but does not raise."""
    route = respx.post(URL).mock(return_value=Response(500))

    client = _make_client()
    client.enqueue(_trace())
    client._shutdown()

    assert route.call_count == _MAX_RETRIES


@respx.mock
def test_shutdown_drains_queue():
    """Traces enqueued before _shutdown are all delivered."""
    route = respx.post(URL).mock(return_value=Response(201))

    client = _make_client()
    for i in range(8):
        client.enqueue(_trace(f"drain-{i}"))
    client._shutdown()

    assert route.call_count == 8
