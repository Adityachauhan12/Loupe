# Item 10 — SDK: loupe.span() context manager

`loupe.span()` lets users record sub-operations *inside* a trace — so the dashboard can show a tree like "agent took 1.5s total: DB lookup 0.3s, LLM call 1.2s."

---

## Sub-step A — ContextVar for trace state

**What changed**

- Added `_TraceContext` dataclass: holds `trace_id`, accumulated `spans`, and `current_span_id` (tracks which span is the current parent for nesting).
- Stored in a `ContextVar[_TraceContext | None]` — set when `@trace` starts, reset when it ends.

**Learnings**

- **`ContextVar` vs `threading.local`.** `threading.local` stores one value per *thread*. `ContextVar` stores one value per *async task* (coroutine). In async code, multiple coroutines can share a thread — `threading.local` would give them all the same value. `ContextVar` gives each coroutine its own isolated copy. Always use `ContextVar` for context you'd normally put in `threading.local` in an async codebase.
- **`token = var.set(value)` + `var.reset(token)`.** This is the safe pattern for scoped ContextVar changes. `set()` returns a token that remembers the previous value. `reset(token)` restores it. This means nested traces work correctly — the inner trace's context doesn't leak into the outer trace after the inner one completes.

**Interview questions**

1. Why use `ContextVar` instead of a global variable for trace state? *(concurrent traces in async code would overwrite each other's state with a global)*
2. What's the difference between `ContextVar`, `threading.local`, and a global? *(global = shared everywhere; threading.local = per thread; ContextVar = per async task)*

---

## Sub-step B — `loupe.span()` context manager

**What changed**

- `@contextmanager` function: reads `_current_trace`, creates a `SpanPayload`, yields it so the user can set attributes (`s.output = ...`, `s.model = ...`), then records `ended_at`, `duration_ms`, and appends to the trace's span list.
- Parent linking: `parent_id = ctx.current_span_id` before yielding; `ctx.current_span_id = span_id` while running; restored after. So nested `with loupe.span(...)` blocks automatically link as parent → child.
- No-op if called outside a `@trace` (no current context) or before `loupe.init()`.

**Learnings**

- **`@contextmanager` turns a generator into a context manager.** The code before `yield` runs on `__enter__`, the code after runs on `__exit__`. Exceptions inside the `with` block are thrown at the `yield` point, so you can catch them there.
- **Yielding the span object** lets the user attach output/metadata after the operation completes — e.g. `s.output = {"rows": results}`. This is the ergonomic pattern: open the span, do your work, attach results.
- **Spans are collected into the trace, not flushed individually.** Everything ships in one POST when the `@trace` decorator's `finally` runs. Fewer HTTP calls, atomic delivery.
- **`current_span_id` restore in `finally`.** If the span block raises, we still restore the parent pointer. Without this, a failed inner span would leave `current_span_id` pointing at a dead span, and all subsequent spans would be mis-parented.

**Interview questions**

1. How does `@contextmanager` work — what do `__enter__` and `__exit__` map to? *(code before yield = __enter__; code after yield = __exit__; exceptions inside the with block are re-raised at the yield point)*
2. How does parent–child linking work for nested spans? *(current_span_id is set to the new span's ID on entry, restored to the previous value on exit — a stack-like discipline using a single variable)*
3. Why collect spans in memory and flush once rather than POSTing each span immediately? *(one HTTP round-trip; atomic: either the whole trace lands or nothing does; simpler retry logic)*
