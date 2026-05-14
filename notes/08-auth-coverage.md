# Item 8 — API key auth on all endpoints

The auth functionality already landed in item 5. This item formalizes it: makes the security scheme show up in OpenAPI/Swagger, and audits coverage across every route.

---

## Sub-step A — Switch from `Header(...)` to `APIKeyHeader`

**What changed**

- Replaced `Header(default=None)` with `APIKeyHeader(name="X-API-Key", auto_error=False)` from `fastapi.security`.
- Functional behavior identical (still raises our own 401 with the same message). The difference is that `APIKeyHeader` registers itself in the OpenAPI `securitySchemes` section, so Swagger UI renders an "Authorize" button.

**Learnings**

- **`auto_error=False` is the right choice when you want custom 401 messages.** With `auto_error=True` (the default), `APIKeyHeader` raises a `403 Forbidden` automatically when the header is missing — which is wrong (should be 401, "missing credentials") and bypasses your own error message. Pass `auto_error=False` and check for missing yourself.
- **Why `APIKeyHeader` exists at all when `Header(...)` works.** Pure-functionally they're equivalent for reading the header value. The difference is *metadata*: `APIKeyHeader` is a security primitive that FastAPI knows to register in `components.securitySchemes` and attach to each route's `security` clause. `Header` is just a parameter source. This affects auto-generated docs and any client codegen that reads OpenAPI to wire up auth.
- **401 vs 403, quick reminder.** 401 = "no valid auth provided, please authenticate." 403 = "we know who you are, you don't have permission for this." FastAPI's defaults sometimes use 403 for missing auth — that's wrong by RFC 7235 but is unfortunately common.

**Interview questions**

1. What's the difference between `APIKeyHeader` and `Header(...)` in FastAPI? *(security metadata in OpenAPI; otherwise functionally similar for reading header values)*
2. When should an API return 401 vs 403? *(401 = missing/invalid credentials; 403 = authenticated but not authorized for this resource)*
3. Why might `auto_error=True` be a problem? *(returns a 403 with a generic message, bypassing your custom error and the correct status code)*

---

## Sub-step B — Route audit

**What changed**

- Grepped for every `@router.*` and `@app.*` declaration: 3 routes under `/v1/traces`, 1 route at `/health`.
- Grepped for `require_api_key`: every `/v1/*` route has it; `/health` does not (intentional).

**Learnings**

- **Liveness probes should never require auth.** If `/health` returned 401, the load balancer or Kubernetes liveness probe would mark the pod unhealthy and kill it. Health endpoints are deliberately outside the auth perimeter.
- **Audit by `grep`, not by inspection.** Three routes is small enough to eyeball, but the discipline of running `grep -nE "@(router|app)\." app/**/*.py` against every change is what catches the case where someone adds a route in a new file and forgets the dependency. In a bigger team, a CI check that fails if a route under `/v1/*` lacks a dependency on `require_api_key` is worth wiring up.

**Interview questions**

1. Should `/health` require authentication? *(no — Kubernetes/LB probes need it to be open; secure liveness leaks no useful info)*
2. How would you enforce in CI that every new `/v1/*` route has an auth dependency? *(static analysis: grep, AST walk of route decorators, or a custom flake8 plugin)*

---

## Sub-step C — Verify via `/openapi.json`

**What changed**

- Confirmed `/openapi.json` lists `APIKeyHeader` in `components.securitySchemes`.
- Confirmed every `/v1/traces*` path has `security=[{"APIKeyHeader": []}]`.
- Confirmed `/health` has no `security` clause.
- Confirmed bad key still returns 401 with our custom message.

**Learnings**

- **`/openapi.json` is your contract.** The spec FastAPI generates is what client SDK generators read to produce typed clients. If a route forgets its security dependency, the SDK won't know to send the key — clients silently get 401s with no idea why.
- **Swagger UI `/docs` reads this too.** The "Authorize" button you see in Swagger is rendered from the `securitySchemes` block. With `APIKeyHeader` registered, users can paste their key once and have it sent on every "Try it out" call. With `Header(...)` they'd have to paste it into every form.

**Interview questions**

1. What's the difference between `/docs`, `/redoc`, and `/openapi.json` in FastAPI? *(/docs = Swagger UI, /redoc = ReDoc UI, /openapi.json = raw spec — both UIs are rendered from the JSON)*
2. Why is the OpenAPI spec a load-bearing artifact, not just docs? *(SDK codegen, client tooling, contract tests, mock servers all read it)*
