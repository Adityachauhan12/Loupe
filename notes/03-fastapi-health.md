# Item 3 — FastAPI app with /health endpoint

---

## Sub-step A — Pinned dependencies

**What changed**

- Created `server/requirements.txt` with `fastapi==0.115.6` and `uvicorn[standard]==0.34.0`.

**Learnings**

- **`uvicorn[standard]` vs plain `uvicorn`.** The `[standard]` extra pulls in `uvloop` (faster event loop, drop-in `asyncio` replacement), `httptools` (fast HTTP parser), `watchfiles` (for `--reload`), and `websockets`. In production, `uvloop` alone is a noticeable perf win — worth the extra deps unless you have a specific constraint.
- **FastAPI sits on top of Starlette.** FastAPI is essentially "Starlette + Pydantic + automatic OpenAPI". When you read a FastAPI traceback that mentions `starlette.routing` or `starlette.middleware`, that's the underlying ASGI framework doing the work. Knowing this helps when you read FastAPI internals.
- **Why not Flask?** Flask is sync-first. It works async via extensions, but the ecosystem fights you. FastAPI is async-native and has Pydantic-based validation baked in. For new LLM/IO-bound services, FastAPI is the default in 2026.

**Interview questions**

1. What's the difference between FastAPI and Starlette? *(Starlette is the ASGI core; FastAPI adds Pydantic validation, dependency injection, and OpenAPI generation)*
2. Why does `uvicorn[standard]` matter in production? *(uvloop replaces the default asyncio loop with a libuv-backed one; httptools replaces the Python HTTP parser; both are large perf wins)*
3. Sync vs async web frameworks — when does async actually help? *(IO-bound workloads with many concurrent slow requests — DB, external APIs, LLM calls. CPU-bound code gets no benefit from async)*

---

## Sub-step B — The FastAPI app and `/health` endpoint

**What changed**

- Created `server/app/main.py` with a `FastAPI()` instance and an `async def health()` route returning `{"status": "ok"}`.

**Learnings**

- **`/health` is a *liveness* check, not a *readiness* check.**
  - **Liveness:** "Is this process alive at all?" Returning 200 unconditionally is fine. Kubernetes restarts the pod if this fails.
  - **Readiness:** "Can this process handle traffic right now?" Should check downstream deps (DB, cache, external services). Kubernetes removes the pod from the load balancer if this fails but doesn't kill it.
  - For a real production service, expose both: `/livez` (no deps) and `/readyz` (checks DB connectivity). MVP `/health` here is the liveness check; we'll add `/readyz` in a later item.
- **`async def` for a route that doesn't await anything.** Still fine — FastAPI runs it on the event loop. If you used `def` (sync) instead, FastAPI runs it in a threadpool. For a trivial response that's strictly faster as `async def` (no thread context switch).
- **`title` and `version` on `FastAPI(...)`.** These flow into the auto-generated OpenAPI schema at `/docs` and `/openapi.json`. Worth setting from day one — it's free metadata.

**Interview questions**

1. What's the difference between a liveness and a readiness probe? *(liveness = restart-if-dead; readiness = remove-from-LB-if-not-serving)*
2. You have a route that doesn't await anything — `def` or `async def`? *(`async def` if you're on FastAPI/Starlette; FastAPI runs sync routes in a threadpool which adds context-switch overhead)*

---

## Sub-step C — venv, install, run, verify

**What changed**

- Created `server/.venv` with `python3.11 -m venv .venv`.
- Installed pinned deps: `.venv/bin/pip install -r requirements.txt`.
- Started uvicorn in the background, curl'd `/health` → got `{"status":"ok"}` with HTTP 200, stopped uvicorn.

**Learnings**

- **One venv per project, never global pip installs.** Global `pip install` mutates the system Python and breaks other projects on the same machine. Venvs isolate per-project deps. `pyenv`, `uv`, and `rye` are alternative ways to manage this — `.venv` directly is the simplest.
- **`.venv/bin/uvicorn` directly vs activating.** Calling the venv binary directly works without `source .venv/bin/activate`. Useful in scripts, Makefiles, CI — `activate` is convenience for interactive shells.
- **`uvicorn app.main:app`** — `app.main` is the import path (resolves to `server/app/main.py` when run from `server/`), `:app` names the `FastAPI()` instance variable. The colon is uvicorn-specific syntax for "module:attribute".
- **`--host 127.0.0.1` for local-only.** `0.0.0.0` binds to all interfaces, exposing the dev server on your LAN. Default to 127.0.0.1 unless you're intentionally exposing.

**Interview questions**

1. Why use a venv instead of global pip? *(per-project isolation; reproducibility; no privileged installs)*
2. What does `uvicorn module:attribute` syntax mean, and how does uvicorn find the app? *(imports the module, looks up the attribute by name, expects an ASGI callable)*
3. Difference between `--host 127.0.0.1` and `--host 0.0.0.0` — when does it matter? *(loopback vs all interfaces; matters for security in dev and for container networking — in a container you usually want 0.0.0.0)*
