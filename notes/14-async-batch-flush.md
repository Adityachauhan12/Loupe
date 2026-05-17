# 14 — SDK: Batched Async Flush with Retry

## What changed

- Rewrote `sdk/loupe/client.py`:
  - `LoupeClient` now spins up a background daemon thread with its own `asyncio` event loop at `__init__` time
  - `enqueue(trace)` replaces `flush(trace)` — non-blocking, uses `loop.call_soon_threadsafe` to push into an `asyncio.Queue`
  - `_worker()` async coroutine drains the queue in batches (`_BATCH_SIZE = 10`), sends concurrently with `asyncio.gather`
  - `_send_with_retry()` retries 5xx/network errors with exponential backoff (1s → 2s → 4s); 4xx = no retry
  - `_shutdown()` is registered with `atexit` — puts a `None` poison pill into the queue and blocks on `thread.join(15s)` to drain before process exit
- Updated `sdk/loupe/core.py`: `_client.flush()` → `_client.enqueue()`
- Added `sdk/tests/test_client.py` — 7 tests covering delivery, non-blocking return, batching, retry on 5xx, no retry on 4xx, exhaust retries, shutdown drain

## Architecture: why a background thread with its own event loop?

The SDK must work in both sync and async host programs. If we used `asyncio.ensure_future` or `loop.create_task`, we'd need the host's event loop — which either doesn't exist (sync app) or creates task-ownership confusion (async app). A separate thread + its own event loop sidesteps both problems:
- The SDK's async work is fully isolated from the host application
- No risk of blocking the host's event loop
- Works identically whether the host is `uvicorn`, a plain `if __name__ == "__main__"`, or a Jupyter notebook

This is the same pattern used by the Sentry Python SDK and the OpenTelemetry Collector's batch exporter.

## Sub-step learnings

### `loop.call_soon_threadsafe` — the only safe way to cross threads into asyncio

`asyncio.Queue` is NOT thread-safe. You cannot call `queue.put_nowait()` from a different thread — it may corrupt the queue's internal state or deadlock. `loop.call_soon_threadsafe(callback)` schedules the callback to run in the loop's thread at the next iteration, which is safe. This is the canonical pattern for "main thread → async worker" communication.

### Poison pill for clean shutdown

Putting `None` into the queue as a shutdown signal is called a "poison pill." The worker processes all real traces ahead of it (queue is FIFO), then when it dequeues `None`, it knows to exit. Advantages over a `threading.Event` shutdown flag:
- Guarantees all previously enqueued items are processed before the worker stops
- No polling — the worker is blocked on `await queue.get()` so it wakes immediately when the pill arrives

### Why `asyncio.gather` for batching?

`asyncio.gather(*coroutines)` runs all coroutines concurrently within a single event loop turn. For a batch of 10 traces, all 10 HTTP requests fly simultaneously — total time ≈ slowest single request, not sum of all. The alternative (`for t in batch: await send(t)`) is serial — 10x slower for the same batch.

### `daemon=True` on the thread

Daemon threads don't prevent process exit. Without it, a Python process with an idle LoupeClient would hang forever waiting for the background thread. The `atexit` handler + `join` gives us a clean drain window; the daemon flag ensures we don't block if `_shutdown` somehow isn't called.

### respx for mocking httpx at the transport layer

`unittest.mock.patch` on `httpx.post` doesn't work with `httpx.AsyncClient.post` — different code paths. `respx` intercepts at the HTTPX transport layer and works correctly with async clients. It also supports `side_effect` lists so you can simulate "fail twice, succeed third time" scenarios precisely.

## Interview questions this covers

**Q: Why not use `threading.Thread` + `httpx.post` (sync) instead of an async worker?**  
A: It works, but each retry `time.sleep()` blocks the thread. With async, `await asyncio.sleep()` yields — the thread can process other queued traces while waiting for the backoff to expire. In high-throughput scenarios (many concurrent traces), this matters.

**Q: What happens to traces if the process is killed with SIGKILL?**  
A: They're lost. `atexit` doesn't fire on SIGKILL (or `kill -9`). For production resilience you'd persist traces to a local WAL (write-ahead log) or SQLite first, then confirm deletion after the server acknowledges. For MVP this is fine — we document it and move on.

**Q: Could the `asyncio.Queue` grow unboundedly? What happens if the server is down for an hour?**  
A: Yes — the queue has no size cap (`asyncio.Queue()` with no `maxsize`). If the server is down, traces pile up in memory. A production fix: `asyncio.Queue(maxsize=1000)` + a policy for what happens when full (drop oldest, drop newest, or block). For MVP, we log an error after `_MAX_RETRIES` and discard — appropriate given this is a dev-tools observability SDK, not a payment processor.

**Q: How does `asyncio.gather` handle partial failure?**  
A: By default, if any coroutine raises, `gather` propagates the first exception immediately (other coroutines may still be running). We prevent this by catching exceptions inside `_send_with_retry` — it logs and returns rather than raises, so `gather` always sees clean completions. Using `return_exceptions=True` on `gather` is the alternative, but explicit handling in the leaf is cleaner.

**Q: Why exponential backoff vs fixed retry interval?**  
A: If 1000 SDK instances all hit a temporarily overloaded server and retry every 1s, they create a retry storm that keeps the server overloaded. Exponential backoff spreads retries over time, giving the server a chance to recover. Adding random jitter (±20% of the backoff interval) would further reduce synchronised retry spikes — a production improvement left as a TODO.
