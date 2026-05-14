# Item 6 — GET /v1/traces list endpoint

The dashboard's "list view" page is served by this. Scoped to the calling API key's project, paginated, sortable by `started_at DESC`, optional `status` filter.

---

## Sub-step A — List response schemas

**What changed**

- Added `TraceListItem` (subset of trace fields needed for the list view — no `input/output/error/metadata` payloads, those come from the detail endpoint).
- Added `TraceList` wrapper with `items`, `limit`, `offset`, `has_more`.
- `TraceListItem` uses `ConfigDict(from_attributes=True)` so Pydantic can build it directly from a SQLAlchemy ORM row.

**Learnings**

- **Don't dump every column into the list view.** `traces.input` and `traces.output` can be huge JSONB blobs. If you return them on every list query, dashboard payloads balloon and the DB has to materialize them every time. The list endpoint sends summary fields; the detail endpoint sends the full row. This is a core API design pattern: **list = summary, detail = full**.
- **`from_attributes=True`** (renamed from `orm_mode=True` in Pydantic v2) lets `TraceListItem.model_validate(orm_row)` pull values from attribute access (`row.id`) instead of dict subscription (`row["id"]`). Without it, you'd have to manually map each row to a dict first.
- **Why include `has_more` and not a `total` count.** `SELECT COUNT(*)` against a filtered table scan is surprisingly slow at scale (Postgres has to scan all matching rows). `has_more` is computed by fetching `limit + 1` rows and checking if the extra one came back — costs one extra row of data, never an extra query. Production systems usually skip exact counts entirely and offer "page 1 of many" UX instead.

**Interview questions**

1. Why have a separate `TraceListItem` schema instead of reusing `Trace`/`TraceIn`? *(list endpoint = summary; sending full JSONB on every list call is wasteful)*
2. How do you tell the client there's another page without running a COUNT? *(fetch limit+1, check if extra row exists; or cursor-based pagination)*
3. What does `from_attributes=True` change in Pydantic? *(switches validation source from `dict[str, V]` to attribute access — ORM-friendly)*

---

## Sub-step B — The GET handler

**What changed**

- `GET /v1/traces?limit=&offset=&status=` — query params validated by FastAPI's `Query(...)` with `ge`/`le`/`max_length` constraints.
- Filters `WHERE project_id = api_key.project_id` always (multi-tenant safety, even though MVP is single-user).
- Sorts `ORDER BY started_at DESC`, uses `OFFSET ... LIMIT (limit + 1)`.
- Returns a `TraceList` with the `has_more` flag computed from the extra row.

**Learnings**

- **Always scope reads by tenant on the server.** Never trust the client to send a `project_id`. The API key resolves to a project, the query uses that project_id — no way for a client to query another tenant's data. This is a hard rule for every read endpoint in any multi-tenant system; even on day one of a single-user MVP, build the habit.
- **`Query(default=..., ge=1, le=200)`** is FastAPI's idiomatic param validation. Out-of-range values return 422 automatically with a structured error. This is *much* better than letting `limit=999999` silently return 999999 rows and OOMing your worker.
- **`alias="status"` for a parameter named `status_filter`.** Python's `status` collides with `fastapi.status` (HTTP code constants), so we rename internally but expose `status` on the wire.
- **`stmt.order_by(...).offset(...).limit(...)`** — SQLAlchemy 2.0 chained query construction. Each call returns a new statement (immutable), so the order of chaining doesn't matter for correctness. The SQL emitted is `ORDER BY ... LIMIT ... OFFSET ...`.
- **Offset pagination's main weakness: deep-offset performance.** `OFFSET 100000 LIMIT 50` means Postgres still scans and discards 100K rows. For deep pagination, cursor-based ("show me rows where `started_at < <previous-last-started-at>`") is much faster and only needs an index. We're MVP — offset is fine until users actually paginate that deep.

**Interview questions**

1. Why scope every read by project_id even when there's only one user? *(habit; multi-tenant safety; later when you add team support nothing breaks)*
2. Walk through the perf of `OFFSET 50000 LIMIT 50` on a 10M row table. *(Postgres scans 50K+50 rows; cursor-based avoids this entirely)*
3. Why constrain `limit ≤ 200` on the API? *(prevents accidental DoS; bounds worst-case query cost)*
4. What does `WHERE project_id = ?` plus `ORDER BY started_at DESC LIMIT 50` cost with our composite index vs without? *(with: single index scan, ~3 buffer reads; without: seq scan + sort + limit, gets worse linearly with row count)*

---

## Sub-step C — Verification

**What changed**

- Seeded 2 extra traces via POST so there are 3 total. Ran 6 test cases against the live endpoint.
- Used `EXPLAIN ANALYZE` to confirm Postgres picked `idx_traces_project_started` for the list query.

**Learnings**

- **`EXPLAIN ANALYZE` after every new indexed query.** Cheap and the only way to know the planner actually uses your index. Common reasons it doesn't: (1) row count too low (planner thinks seq scan is cheaper — true at 3 rows!), (2) statistics stale (`ANALYZE table` to refresh), (3) the index doesn't cover the query's filter+sort. Here it did pick our composite index even at 3 rows.
- **`Index Scan using idx_traces_project_started`** in the plan output is what you want. Other possibilities: `Bitmap Index Scan` (for IN-list filters), `Seq Scan` (no index used — usually a problem at scale), `Index Only Scan` (covered index, even faster — would require including `started_at` in the index columns *and* `id`, plus a VACUUM).
- **Test the 422 paths.** It's tempting to only test happy + 401. `limit=999` returned a structured 422 because of our `le=200` constraint — that's input validation working at the FastAPI layer, before any DB code runs.

**Interview questions**

1. How do you verify a query is actually using an index? *(`EXPLAIN ANALYZE`; look for "Index Scan" vs "Seq Scan")*
2. What's an "Index Only Scan" and when does Postgres pick it? *(query can be answered entirely from the index without visiting the heap; requires covering index + a visibility-map-clean heap)*
3. The planner picks a `Seq Scan` even though you have an index. List 3 reasons. *(small table where seq scan wins; stale statistics; index doesn't fit the query; query doesn't filter on the indexed columns selectively)*
