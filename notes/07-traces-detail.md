# Item 7 — GET /v1/traces/{id} detail endpoint

Returns one trace with full input/output payloads + all its spans nested. The dashboard's trace-detail page calls this once per page view.

---

## Sub-step A — Detail response schemas (`SpanOut`, `TraceDetail`)

**What changed**

- `SpanOut` — every column from the `spans` table, including the full JSONB payloads (`input`, `output`, `error`).
- `TraceDetail` — every column from the `traces` table plus a nested `spans: list[SpanOut]`.
- Both use `ConfigDict(from_attributes=True)` so Pydantic builds them straight from ORM rows.
- The `metadata` field on the wire is populated from the ORM attribute `extra_metadata` via `Field(validation_alias="extra_metadata")`.

**Learnings**

- **`validation_alias` is the right fix for the `metadata` rename.** We renamed the Python attribute to `extra_metadata` to dodge `Base.metadata`, but on the wire we want users to see `metadata` (matching the DB column name and the CLAUDE.md schema). `validation_alias` tells Pydantic "when reading from an object, look for `extra_metadata`; when serializing to JSON, output the field as `metadata`." Cleanest workaround for the SQLAlchemy reserved-name issue.
- **Two response schemas for the same table is fine.** `TraceListItem` (summary) and `TraceDetail` (full) are intentional. Don't try to share one schema with optional fields — you'd lose type safety and Pydantic's auto-validation would get fuzzy.
- **Pydantic v2 handles nested ORM relationships transparently.** When `TraceDetail.spans: list[SpanOut]` is being built from a `Trace` ORM object, Pydantic walks `trace.spans` (the SQLAlchemy relationship) and validates each one as a `SpanOut`. No manual loop needed.

**Interview questions**

1. Why two schemas (list vs detail) for the same underlying table? *(different fields, different sizes, different perf characteristics; sharing schemas hides the cost of the JSONB payload)*
2. How does Pydantic v2 know to walk a SQLAlchemy relationship like `trace.spans`? *(`from_attributes=True` + the relationship is a normal attribute that yields a list when accessed)*

---

## Sub-step B — GET handler with `selectinload`

**What changed**

- `GET /v1/traces/{trace_id}` — UUID path param (FastAPI validates the format automatically).
- Query: `SELECT trace WHERE id=? AND project_id=? OPTIONS(selectinload(Trace.spans))`.
- Returns the `Trace` ORM object directly; FastAPI runs it through `TraceDetail.model_validate()` for response.
- 404 if the trace doesn't exist *or* it exists but belongs to a different project (intentional — don't leak existence to the wrong tenant).

**Learnings**

- **`selectinload(Trace.spans)`** runs a second query — `SELECT * FROM spans WHERE trace_id IN (?)` — to fetch all spans for the parent trace in one round-trip. This is the right strategy for one-to-many relationships in async SQLAlchemy.
  - **Alternative 1: lazy load.** Don't ask for `selectinload`, and let SQLAlchemy fetch spans the first time you access `trace.spans`. **This crashes in async** because lazy loading is synchronous; you'd get `MissingGreenlet`. Async code must explicitly load relationships up front.
  - **Alternative 2: `joinedload`.** Uses a SQL `LEFT OUTER JOIN`. Returns one row per span and duplicates parent columns — for a trace with 50 spans you get 50 rows back, each containing the full trace data. Wasteful for big payloads. `selectinload` does two queries instead of one big one and is usually faster for one-to-many.
  - **Alternative 3: `subqueryload`.** Similar to selectinload but uses a correlated subquery. Older pattern; `selectinload` is generally preferred now.
- **404 on cross-tenant access is intentional.** If the trace exists but belongs to another project, we return 404 (not 403). Returning 403 would tell an attacker "this ID is valid, you just can't see it" — an information leak. 404 says "no such resource in your scope," which is what's actually true from the caller's perspective.
- **FastAPI's automatic UUID validation on path params.** Declaring `trace_id: uuid.UUID` makes FastAPI return 422 for malformed UUIDs *before* the route runs. No SQL is executed, no DB connection is held.

**Interview questions**

1. Explain `selectinload` vs `joinedload` vs lazy load — when do you pick which? *(selectinload = 2 queries, no duplication, default for async; joinedload = 1 query with JOIN, duplicates parent, good for to-one; lazy = sync only, breaks in async)*
2. Why return 404 instead of 403 for cross-tenant access? *(prevents existence-leak; the resource genuinely doesn't exist within the caller's scope)*
3. What happens if you try to access a SQLAlchemy relationship in an async context without explicit loading? *(`MissingGreenlet` exception; the implicit DB call can't run on the event loop)*

---

## Sub-step C — Verification

**What changed**

- Tested four scenarios against the live endpoint: happy path (returns full trace + 2 spans), 404 on random UUID, 422 on malformed UUID, 401 on bad key.

**Learnings**

- **The four error classes for a GET-by-ID endpoint.** Memorize these:
  - **401** — auth missing or invalid.
  - **404** — resource not found in this scope (or genuinely not found).
  - **422** — request shape invalid (bad UUID, bad query param).
  - **500** — server bug; shouldn't happen, but log everything when it does.
  - Some teams also use **403** for "authenticated but not authorized" — Loupe collapses 403 into 404 to prevent existence leaks, as noted above.
- **`uuid_parsing` 422 error** is what FastAPI returns for a path UUID that doesn't parse. Note this happens *before* auth runs, which is correct — there's no point hitting the DB with garbage. (If the order were reversed and auth ran first, a missing auth would mask a bad UUID — a confusing debugging story.)

**Interview questions**

1. List the four most common HTTP error classes for a GET-by-ID endpoint and what each means. *(401, 403/404, 422, 500)*
2. Why does FastAPI validate path params before running dependencies? *(saves a DB hit; the request is malformed regardless of who's calling)*
