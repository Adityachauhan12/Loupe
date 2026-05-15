# Item 9 — SDK: @loupe.trace decorator

The SDK is what the user actually adds to their agent — the whole point of Loupe from a user's perspective.

---

## Sub-step A — Package setup (`pyproject.toml`)

**What changed**

- Created `sdk/pyproject.toml` with `setuptools.build_meta` build backend, package name `loupe-sdk`, Python ≥3.11, deps `httpx` and `pydantic`.
- Dev extras: `pytest`, `pytest-asyncio`, `respx` (HTTP mocking for tests).
- `pip install -e ".[dev]"` installs it in editable mode — changes to `sdk/loupe/` take effect immediately without reinstalling.

**Learnings**

- **`setuptools.build_meta` vs `setuptools.backends.legacy:build`.** The latter is newer syntax not yet supported by older setuptools versions. `build_meta` is the stable choice that works across pip versions.
- **Editable installs (`-e`).** Instead of copying files into `site-packages`, pip just adds a `.pth` file pointing at your source directory. Edits are live immediately. Essential for development; you'd never use `-e` in production.
- **Why `httpx` over `requests`.** `httpx` has an identical API to `requests` (easy to learn) but also supports async. The SDK currently uses sync HTTP but the async path is available when we add `loupe.span()` context manager. `requests` has no async support.

**Interview questions**

1. What does `pip install -e` actually do on disk? *(adds a .pth file in site-packages pointing at your source dir; no file copy)*
2. Why would an SDK prefer `httpx` over `requests`? *(async support; near-identical API; single dep handles both sync and async use cases)*

---

## Sub-step B — Wire format models (`models.py`)

**What changed**

- `SpanPayload` and `TracePayload` — Pydantic models matching the server's `SpanIn`/`TraceIn` schemas exactly.
- SDK owns its own copy rather than importing from the server — they're separate packages with different release cycles.

**Learnings**

- **SDK wire models are intentionally separate from server schemas.** If the server renames a field in v2, the SDK v1 still needs to work. Sharing a schema package would couple their release cycles. Two copies of a 30-line model is the right tradeoff.
- **`TracePayload.spans` is a flat list, not a tree.** Parent-child relationships are expressed via `parent_span_id`. The server stores it flat; the dashboard builds the tree at render time. The SDK never needs to care about tree structure — it just records spans and ships them.

---

## Sub-step C — HTTP client (`client.py`)

**What changed**

- `LoupeClient.flush(trace)` — synchronous, retries up to 3 times on 5xx errors, gives up immediately on 4xx (retrying won't help if the server rejected the request), logs warnings on failure without raising.

**Learnings**

- **Don't raise exceptions from the client.** If Loupe can't send a trace, the *user's agent should still run*. Throwing means a network blip in Loupe crashes the thing being observed. Swallow errors, log them.
- **Retry on 5xx, not on 4xx.** 4xx = client error (bad auth, invalid data) — retrying sends the same bad request again. 5xx = server error — the server might recover. Always distinguish these in retry logic.
- **Synchronous flush for now.** Simple and debuggable. Item 13 (batched async flush) replaces this with a background queue. The interface (`client.flush(trace)`) stays the same — only the implementation changes.

**Interview questions**

1. Why should an SDK client never raise exceptions to the caller? *(instrumentation must not affect the application's correctness)*
2. Retry on 5xx but not 4xx — explain why. *(4xx = caller's fault, retrying wastes time; 5xx = server's fault, may resolve)*

---

## Sub-step D — `@trace` decorator (`core.py`)

**What changed**

- `loupe.init(api_key, host)` — sets the global client. No init = decorator is a no-op (function runs normally).
- `@loupe.trace` and `@loupe.trace(name="...")` — both forms work.
- Records `started_at`, `ended_at`, `duration_ms`, serialised `input` (args + kwargs), `output` (return value), `error` (exception info + traceback) on the trace.
- Uses a `try/finally` block — the trace is always flushed even if the function raises, and the exception always propagates.

**Learnings**

- **`try/finally` not `try/except`.** The decorator should be invisible to the caller. Using `except` would swallow the exception. `finally` records the trace and lets the exception continue propagating. This is the core invariant: *Loupe never changes your program's behaviour*.
- **The `_fn` parameter trick for dual-form decorators.** `@loupe.trace` passes the function as `_fn`; `@loupe.trace(name="...")` passes `None`. Checking `if _fn is not None` lets one function handle both forms cleanly.
- **`functools.wraps(fn)`** copies the wrapped function's `__name__`, `__doc__`, `__module__` onto the wrapper. Without it, every decorated function looks like it's named `wrapper` in tracebacks and `help()` output.
- **No-op when uninitialised.** If `loupe.init()` was never called, `_client` is None and the decorator returns immediately. This means you can ship code with `@loupe.trace` decorators and they'll do nothing until the user configures a key — zero surprise for users who haven't set up Loupe yet.
- **`_safe_serialize` + `_to_jsonable`.** Agent arguments can be anything: dataclasses, numpy arrays, custom objects. We need to send JSON to the server. `_to_jsonable` recursively converts known types and falls back to `str(obj)` for unknowns. Never raises — worst case you get a stringified repr.

**Interview questions**

1. Why use `try/finally` instead of `try/except` in the decorator? *(finally runs whether or not an exception occurred; except would swallow it)*
2. What does `functools.wraps` do and why does it matter? *(copies __name__, __doc__, etc. from wrapped function; tracebacks and introspection tools stay correct)*
3. How do you write a decorator that works both as `@dec` and `@dec(arg=...)`? *(check if the first positional arg is a callable — if yes, decorate immediately; if no, return the decorator)*
