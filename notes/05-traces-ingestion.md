# Item 5 — POST /v1/traces ingestion endpoint

This is the first endpoint that does real work: SDK clients call it with one trace + N spans, server persists them in a single transaction.

---

## Sub-step A — Pydantic schemas (`schemas.py`)

**What changed**

- `SpanIn` and `TraceIn` Pydantic models mirror the wire format the SDK will send. `TraceIn.spans: list[SpanIn]` — one POST carries everything.
- `TraceCreated` is the response: just `trace_id` and `span_count`.
- All schemas use `ConfigDict(extra="ignore")` so unknown fields from older SDK versions don't 422 the request.

**Learnings**

- **`extra="ignore"` vs `extra="forbid"` vs `extra="allow"` on Pydantic models.** For server-side request validation, `ignore` is the right default for a public ingestion endpoint — you want forward-compatibility when older clients send extra fields. `forbid` is good for internal config. `allow` is rarely what you want — it preserves unknown fields, which makes schema drift invisible.
- **`Field(default_factory=list)` not `Field(default=[])`.** Mutable defaults in Python class attributes are a classic footgun; every instance would share the same list. Pydantic catches this at model definition, but the habit matters anywhere Python class state lives.
- **`datetime` parsing.** Pydantic v2 accepts ISO 8601 strings (with or without timezone), Unix timestamps, and `datetime` objects. The wire format choice here is "ISO 8601 with timezone" — strongly recommended for any system timeline data so you avoid timezone ambiguity disasters.
- **Why have request schemas at all when SQLAlchemy could read JSON directly?** Three reasons: (1) input validation at the boundary, with clear 422 errors; (2) decoupling the wire format from the DB schema (we can rename columns without breaking clients); (3) OpenAPI generation gives clients a contract.

**Interview questions**

1. When would you use `extra="forbid"` vs `extra="ignore"`? *(forbid for internal/config schemas where typos matter; ignore for public APIs to allow forward-compatibility)*
2. Why separate Pydantic request schemas from SQLAlchemy models? *(boundary validation; wire/DB decoupling; OpenAPI contract; some fields like password are input-only and never persisted)*
3. If a client POSTs `metadata` (a dict) — what does Pydantic do under the hood to validate it? *(coerces JSON to dict, validates recursively if there's nested model typing; here just checks `dict[str, Any]` which is permissive)*

---

## Sub-step B — API key auth dependency (`auth.py`)

**What changed**

- `hash_key(raw) -> str` uses sha256. **Hashes are stored, raw keys are not.**
- `generate_key()` returns `(raw, hash)`. Raw starts with `lp_` prefix + 32 bytes of `secrets.token_urlsafe`. The user sees the raw value exactly once.
- `require_api_key()` is a FastAPI dependency: reads `X-API-Key` header, looks up the hash in the `api_keys` table, raises 401 on mismatch, updates `last_used_at`, returns the `ApiKey` ORM object.

**Learnings**

- **Never store raw API keys.** If the DB leaks, attackers can authenticate as everyone. Hashing means a leak forces them to brute-force each key (and our keys have 32 bytes of entropy from `secrets.token_urlsafe` — practically un-brute-forceable). The hash is essentially what bcrypt-for-passwords does, except sha256 is fine for high-entropy random keys (we don't need slow KDFs because there's no dictionary to crack — they're random bytes).
- **Why sha256 and not bcrypt for API keys?** Bcrypt and argon2 are designed for *low-entropy* secrets (passwords) where you need to slow down dictionary attacks. API keys have 256 bits of randomness — slowing the lookup by 100ms per request just hurts you, not the attacker. sha256 (or hmac-sha256 with a server pepper) is the right tool here.
- **`secrets.token_urlsafe` vs `random.choices`.** Always use `secrets` for anything authentication-related. `random` is a PRNG seeded in a predictable way and is not cryptographically secure. `secrets` uses the OS's CSPRNG.
- **Prefix the key with a brand string (`lp_`).** Two reasons: (1) lets you write secret-scanning regex in CI to catch keys committed to Git; (2) makes the key visually identifiable as a Loupe key in logs/tickets without revealing it. GitHub does this (`ghp_`), Stripe does it (`sk_test_`), etc.
- **Constant-time compare?** For *random high-entropy* keys, hash-and-compare is constant-time enough — you're comparing hashes, not raw secrets, and equal-length hex strings don't have a useful timing side channel. For passwords (low entropy + KDF), you'd use `hmac.compare_digest`.
- **Updating `last_used_at` on every request.** Useful for "show me keys that haven't been used in 90 days, candidates for cleanup". Cost: a write per request — at scale you'd batch this (write only if last update was >5 min ago) but for MVP simple is fine.

**Interview questions**

1. Why hash API keys before storing? Why is sha256 fine here when you'd use bcrypt for passwords? *(leak resistance; entropy difference between random keys and human-chosen passwords)*
2. Why prefix API keys with a brand string like `lp_`? *(secret scanning, visual identification, key-type routing)*
3. Where should the auth check happen — inside the route or in middleware? *(FastAPI dependency is the idiomatic answer; middleware works but loses access to typed dependencies; gateway-level auth is the production answer at scale)*
4. What's `secrets.token_urlsafe` doing internally? *(reads `os.urandom`, base64url-encodes; CSPRNG, not seeded PRNG)*

---

## Sub-step C — The router (`routers/traces.py`)

**What changed**

- `POST /v1/traces` accepts a `TraceIn`, the `ApiKey` dependency, and an `AsyncSession`.
- Uses Postgres-specific `insert(...).on_conflict_do_nothing(index_elements=["id"])` for both the trace and the spans.
- All inserts happen in one transaction (single `await db.commit()`). If the spans insert fails, the trace insert is rolled back.
- Returns 201 with `{trace_id, span_count}`.

**Learnings**

- **Idempotency on retry.** If the SDK times out waiting for our response but the request actually succeeded, the SDK retries with the same trace ID. Without `ON CONFLICT DO NOTHING`, the second POST would 409 or 500 — visible as an error in the user's app. With it, re-delivery is a no-op and we return the same 201. This is **the most important pattern in any write API** that you don't want to lose data from.
- **Bulk insert via `insert(Span).values([{...}, {...}])`.** One round-trip instead of N. SQLAlchemy turns this into a single `INSERT ... VALUES (...), (...), (...)` statement. For our use case (typically 5–50 spans per trace) the savings are real.
- **`insert` from `sqlalchemy.dialects.postgresql`** (not from `sqlalchemy` directly). The base `insert` doesn't have `on_conflict_do_nothing` — that's a Postgres extension. Importing the dialect-specific one gives you upsert semantics. If you ever want cross-database portability you'd have to write a different conflict-handling path, but for MVP we're Postgres-only.
- **Transaction scope = the FastAPI dependency lifetime.** `get_db()` yields a session, the route runs, the session closes when the request ends. If you `await db.commit()` mid-route and then throw, what's already committed *stays committed* — which is why we batch all inserts and commit once at the end.
- **The `metadata` attribute trap (again).** When using ORM-level `insert(Trace).values(**dict)`, the dict keys must be **Python attribute names**, not column names. We named the attribute `extra_metadata` (to avoid colliding with `Base.metadata`) but the *column* is still `metadata`. We hit this as a 500 during testing — `AttributeError: 'MetaData' object has no attribute '_bulk_update_tuples'`. SQLAlchemy was trying to use the `Base.metadata` object as a column descriptor. **Lesson:** rename the attribute, use the new attribute name everywhere except raw SQL.

**Interview questions**

1. Walk through the idempotency story for this endpoint. What happens if the SDK retries the same trace ID? *(`ON CONFLICT DO NOTHING`, returns same 201)*
2. Why bulk-insert spans in one statement vs a loop? *(one network round-trip; one transaction; one log entry)*
3. How would you handle partial success — trace inserts but spans fail? *(by design we don't; everything is in one transaction so partial failure → full rollback; alternative is two-phase: write trace, return 200, then async-process spans, but it complicates the SDK's "did my data land?" question)*
4. Bonus footgun: you have an ORM column `metadata` — what breaks and how do you work around it? *(name collision with `Base.metadata`; rename Python attr, keep DB column name via positional arg to `mapped_column`)*

---

## Sub-step D — Seeding a test project + API key

**What changed**

- `server/scripts/create_project.py` — a small async script that creates a project, generates an API key, prints the raw key once.

**Learnings**

- **The "show key once" pattern.** You can't show the raw key again later because the DB only has the hash. This is the same UX as AWS access keys, GitHub PATs, Stripe API keys. Be explicit: "save this now, you won't see it again."
- **Why a script vs an HTTP endpoint for now?** This is a single-user MVP. CLAUDE.md says no signup/login flow, no admin UI. A CLI script is the right shape — it runs against the dev DB and gives you a working key without spinning up admin endpoints we'd just delete later.
- **`asyncio.run(main())` for a one-shot script.** When using async SQLAlchemy from a script, this is the bridge — it opens the event loop, runs your coroutine, closes the loop. The session must be created inside the coroutine, not at module scope.

**Interview questions**

1. Why is the raw API key only shown once? *(it's not stored in plaintext; only the hash is in the DB)*
2. How would you handle key rotation? *(generate new key for the user; let them swap clients to use it; revoke old key after they confirm; never show the old raw key again)*

---

## Sub-step E — End-to-end verification

**What changed**

- Started uvicorn, posted a sample trace with two spans, verified 201 response with `{trace_id, span_count: 2}`.
- Negative tests: bad API key → 401, missing header → 401.
- Idempotency test: same trace ID twice → both succeed (201), no duplicate rows.
- Direct DB query confirmed: trace row + 2 spans persisted with correct `parent_span_id` linking.

**Learnings**

- **Always test the unhappy path immediately.** It's easy to declare success on the 200 case and forget that 401 is silently 500-ing. Three lines of curl saves an embarrassing bug later.
- **Test idempotency by literally sending the same payload twice.** This is the single most useful test for a write API. If your test suite has zero of these, you have a reliability gap.
- **Verifying via the DB directly, not the API.** Until we have a `GET /v1/traces` endpoint (item 6), the DB is the only ground truth. `docker exec loupe-db psql -c "..."` is the canonical "did the row actually land" check.

**Interview questions**

1. You're testing a new write endpoint. What are the four scenarios you'd cover before merging? *(happy path, auth failure, validation failure, idempotent retry)*
2. How would you test idempotency in an automated test? *(POST twice with the same ID; assert one row in the DB; assert response is identical)*
