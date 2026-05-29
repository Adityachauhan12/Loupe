# 20 — CineRater example + SDK atexit bug

## What changed

- `examples/cinerater/data.py` — 25-movie hardcoded catalogue
- `examples/cinerater/tools.py` — `search_movies` + `get_movie_details`, wrapped in `loupe.span(type="tool")`
- `examples/cinerater/agent.py` — `@loupe.trace` entry point + two Groq LLM calls
- `examples/cinerater/{requirements.txt,.env.example,README.md}` — quickstart
- `sdk/loupe/client.py` — **rewrote to sync httpx.Client + queue.Queue**, fixed an `atexit during shutdown` bug

## Why CineRater pehle, deploy nahi

Deploy se pehle SDK ko ek **real agent ke saath dogfood** karna chahiye tha. Reason:
- Local pe SDK bugs pakdo, prod pe nahi
- Generated traces seed data ban jaate hain demo ke liye

Aur asli mein — pehli hi run pe ek SDK bug nikla. Agar deploy karke pakadte, render ke logs grep karne padte. Local pe stack trace turant.

## Sub-step learnings

### Hardcoded mock data > live API

CineRater 25 movies ek Python list mein rakhta hai. Choice options the:
1. **Hardcoded** — zero deps, deterministic, demo reliable
2. **TMDB API** — real data, but network dep + 2nd API key + rate limits
3. **Local JSON** — bich ka raasta

Hum #1 chuna kyunki **demo reliability > data realism**. Screencast record karte waqt TMDB down ho gaya toh? Hardcoded mein woh issue nahi.

> *Interview Q:* Mock data se demo karna kya cheating hai? *(no — agent ki **logic** dikhana hai, data source nahi. Tool calls ka pattern same hai chahe data hardcoded ho ya live API se.)*

### Tool spans manually wrap, LLM spans auto

Dekho `tools.py` mein har function `loupe.span(name, type="tool")` ke andar hai:

```python
def search_movies(...):
    with loupe.span("search_movies", type="tool", input=inputs) as s:
        results = ... # filter logic
        s.output = {"count": len(results), "movies": results}
        return results
```

But `agent.py` ke `_parse_query` mein Groq call ke around koi `with loupe.span(...)` nahi hai — yeh **automatic** hai kyunki `loupe.instrument_groq(groq_client)` ne `client.chat.completions.create` ko patch kar diya hai.

**Reason:** LLM calls universal hain — har Groq/OpenAI/Anthropic SDK call mein same shape ka data (model, tokens, cost, messages) hai, toh ek hi baar instrumentation likh ke sab apps ke liye reuse kar sakte hain. **Tool calls custom hain** — har app ke alag tools hote hain, unka shape SDK pehle se nahi jaanta, isliye user ko explicitly wrap karna padta hai.

> *Interview Q:* SDK ko auto-detect kyun nahi karta tool calls? *(could try Python frame inspection / sys.settrace, but that's heavy + brittle + leaks abstraction. Explicit wrapping is the standard pattern — LangSmith, LangFuse, OpenLLMetry sab yehi karte hain.)*

### Agent flow: LLM → tool → tool → LLM

```
recommend("recommend a thriller from 2023")
  ├─ llm  groq.chat       (parse → {"genre": "Thriller", "year": 2023})
  ├─ tool search_movies   (filter catalogue → 3 candidates)
  ├─ tool get_movie_details (top 1)
  ├─ tool get_movie_details (top 2)
  └─ llm  groq.chat       (write final recommendation)
```

Yeh **classic ReAct-ish agent shape** hai — LLM decides, tool executes, LLM synthesizes. Real-world agents (LangChain, LangGraph) ka basic skeleton yehi hai, multi-step loops ke saath. CineRater single-shot hai (no loop), so simpler.

> *Interview Q:* Kyun nahi function calling / tool-use API use kiya parse step ke liye? *(would let the LLM pick the search filters AND call search_movies in one round-trip. Cleaner. But for the demo, the two-step JSON-mode-then-tool flow makes the span tree more interesting to look at, and the failure modes more interesting to replay.)*

## The SDK bug — atexit-during-shutdown race

### Symptom

Pehli baar agent chalaane pe:
```
loupe: unexpected error delivering trace ab8a2c1f-...:
  can't register atexit after shutdown
```

Trace server tak pahuncha nahi (`GET /v1/traces` empty).

### Root cause

Original architecture: `httpx.AsyncClient` + asyncio worker thread + `asyncio.Queue`.

Sequence of doom:
1. `recommend()` returns → `@loupe.trace`'s finally block enqueues the trace
2. `print(...)` runs → main thread exits
3. **Python enters atexit phase** (sets `atexit_lock`)
4. `_shutdown()` atexit hook fires → puts poison pill, `thread.join(timeout=15)`
5. Worker thread picks up the trace, calls `await http.post(...)`
6. Inside httpx async stack (httpcore + anyio), some lazy resource setup calls `atexit.register()`
7. Python's atexit module: "**lock held, can't register, RuntimeError!**"
8. Exception caught by `except Exception` in `_send_with_retry`, logged, trace silently dropped

### Why this happens specifically with async httpx

httpx **sync** `Client` does its setup eagerly in `__init__`. httpx **async** `AsyncClient` defers a lot — anyio task groups, event-loop-bound resources — to first use. That "first use" can land inside the atexit window if the trace is enqueued at the very end of the script.

### Fix

Switch to **sync httpx.Client + `queue.Queue` + sync worker thread**. Architecture is now:
- `enqueue()` puts on a thread-safe `queue.Queue` (no asyncio)
- Worker thread loops: `queue.get()` → `_http.post()` → `task_done()`
- `_shutdown()` sets a flag (block further enqueues), calls `queue.join()` (waits for in-flight traces), then poison-pills the worker

httpx.Client lives for the whole client lifetime, created in `__init__`. No lazy setup during shutdown.

This is the **same pattern Sentry SDK, Datadog SDK, PostHog SDK use** for their background flush threads. Async didn't buy us anything — single-flight HTTP requests don't benefit from asyncio.

### Tradeoff lost

The original async code had a `_BATCH_SIZE = 10` concurrency limit — could send up to 10 traces in parallel per drain cycle. The sync version sends serially. For MVP scale (a few traces per second max) this is fine. If we ever needed real throughput, the sync worker could spawn a `ThreadPoolExecutor` with N workers — much simpler than asyncio.

> *Interview Q:* Async vs sync background workers in SDKs — kab kya? *(async pays off when you have many concurrent in-flight network calls — e.g. fan-out fetches. For a single-flight queue drain, sync is simpler, has fewer failure modes, and avoids loop-vs-atexit races like this one.)*

> *Interview Q:* `queue.join()` vs `thread.join()` ka farq? *(thread.join waits for the THREAD to exit. queue.join waits for all PUT items to be marked `task_done`. We need both: queue.join ensures the trace is sent, then we poison-pill the worker and thread.join lets it exit cleanly.)*

> *Interview Q:* "atexit during shutdown" jaisa race fir se aaye toh kaise debug karega? *(reproduce locally with a short-lived script + enqueue-then-exit pattern. Add `faulthandler` or `threading.enumerate()` at the atexit hook to see what threads are mid-flight. Look at the offending library's source for any module-level `atexit.register` calls.)*

## Verification

```
$ sdk/.venv/bin/python -m examples.cinerater.agent "recommend a thriller from 2023"
Query: recommend a thriller from 2023
I recommend "Anatomy of a Fall" (2023) directed by Justine Triet. ...
```

(No error message.)

```
$ curl -s -H "X-API-Key: lp_..." http://localhost:8000/v1/traces/<id> | jq '.spans[] | {type, name, duration_ms}'
llm   groq.chat            178ms
tool  search_movies          0ms
tool  get_movie_details      0ms
tool  get_movie_details      0ms
llm   groq.chat            394ms
```

All 5 spans present, structure correct.

```
$ cd sdk && .venv/bin/python -m pytest tests/ -q
10 passed in 6.21s
```

No regressions in SDK tests.
