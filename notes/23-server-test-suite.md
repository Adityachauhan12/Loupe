# 23 — Server Test Suite (and the async testing rabbit hole)

> This note covers writing the server's first test suite (44 tests). It's the
> most *educational* item in the whole project — not because the tests are hard,
> but because of WHY it took so long. The struggle was real systems learning:
> async event loops, database connection lifecycles, and ORM relationship
> resolution. Read this when you want to understand how those three things
> actually work.

---

## The objective (what & why)

**Before:** `server/tests/` was empty. The SDK had tests, but the **server had
zero**. Every endpoint — ingest a trace, list traces, get a trace, replay —
was untested.

**Why this mattered NOW:** We were about to build the v2 replay engine (the most
complex code in the project). The rule we agreed on: *you cannot test a complex
new feature safely if the foundation it sits on is untested.* If the replay
engine accidentally broke `GET /v1/traces`, nobody would know.

So: write tests for everything that already exists, THEN build replay on top.

**The goal:** real coverage of every endpoint — happy paths, auth failures,
edge cases — running against a real Postgres database, wired into CI.

---

## The payoff: 2 real bugs the tests caught

This is the part that proves tests aren't busywork. Both bugs were **invisible by
clicking around** — only tests found them.

### Bug 1 — the cost calculation was wrong for half our models

The code that estimates LLM cost:
```python
_COST_PER_M = {
    "gpt-4o":      (2.50, 10.00),   # $ per 1M tokens
    "gpt-4o-mini": (0.15,  0.60),
    ...
}

def _estimate_cost(model, ...):
    for prefix, rates in _COST_PER_M.items():
        if model.startswith(prefix):   # ← THE BUG
            return ...
```

**The problem:** `"gpt-4o-mini".startswith("gpt-4o")` is `True`. Since `gpt-4o`
comes first in the dict, a `gpt-4o-mini` call gets billed at **gpt-4o rates** —
about **16× too expensive**. Every mini-model replay would report wrong cost.

**The test that caught it:**
```python
def test_prefix_matching(self):
    cost = _estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
    assert cost == Decimal("0.750000")   # FAILED — got 12.50 instead
```

**The fix:** check the *longest* prefix first, so the specific name wins:
```python
for prefix, rates in sorted(_COST_PER_M.items(), key=lambda x: -len(x[0])):
```

**Lesson:** `startswith` + a dict = silent precedence bugs whenever one key is a
prefix of another. This is a classic. Now you'll spot it forever.

### Bug 2 — a new DB column silently broke loading EVERY trace

In Phase 3 we added `branched_from_span_id` to the `traces` table (a FK to
`spans.id`). Innocent-looking. But it broke the ORM completely.

**Why:** SQLAlchemy now saw **two foreign-key paths** between `traces` and `spans`:
1. `spans.trace_id → traces.id`   (a span belongs to a trace — the normal one)
2. `traces.branched_from_span_id → spans.id`   (the new one)

When you write `Trace.spans` (give me a trace's spans), SQLAlchemy asked:
*"which FK do I follow?"* — and refused to guess. Result: loading any trace with
spans threw `Could not determine join condition... multiple foreign key paths`.

**In production this would have broken the entire trace detail page.** It only
surfaced because a test did `GET /v1/traces/{id}` and read `.spans`.

**The fix:** tell SQLAlchemy explicitly which FK defines the parent/child link:
```python
spans: Mapped[list[Span]] = relationship(
    back_populates="trace",
    foreign_keys="[Span.trace_id]",   # ← use THIS fk, not branched_from_span_id
)
```

**Lesson:** the moment two tables have more than one FK between them, every
relationship between them becomes ambiguous and needs an explicit `foreign_keys`.
Adding a "harmless" column can break things far away. Tests are how you find out.

---

## Why it took so long: the async testing rabbit hole

Writing the tests was fast. Making them **run** took most of the time. Here's the
honest story of each wall we hit, because each one teaches a real systems concept.

### Background: what makes async DB testing hard

Three things have to cooperate:
1. **The event loop** — the thing that runs all your `async` code.
2. **The database connection** (asyncpg) — a live network socket to Postgres.
3. **The ORM** (SQLAlchemy) — builds SQL and manages sessions.

The golden rule that caused ALL our pain:

> **An asyncpg connection is bound to the event loop it was created in. If you
> touch it from a different loop, it crashes.**

Most of our errors were variations of *"a connection made in loop A is being used
or closed in loop B."*

### Wall 1 — `ScopeMismatch` (anyio vs asyncio)

First run: `ScopeMismatch: session scoped fixture anyio_backend...`. We were
mixing two async test systems (`anyio` and `pytest-asyncio`). They fought.

**Fix:** commit to one (`pytest-asyncio`), remove the `@pytest.mark.anyio`
decorators. **Lesson:** pick one async test framework; don't mix.

### Wall 2 — `CircularDependencyError` creating tables

`create_all` couldn't decide the order to create tables, because `traces` and
`spans` point at *each other*:
- `spans.trace_id → traces`  (need traces first)
- `traces.branched_from_span_id → spans`  (need spans first)

A chicken-and-egg cycle.

**Fix:** mark the newer FK as "add this constraint *after* both tables exist":
```python
ForeignKey("spans.id", use_alter=True, name="fk_traces_branched_from_span")
```
`use_alter=True` tells SQLAlchemy: create both tables first, then `ALTER TABLE`
to add this one FK. Cycle broken.

**Lesson:** circular FKs are legal but need `use_alter` so the schema can be built
in a valid order.

### Wall 3 — `Task got Future attached to a different loop` (the big one)

This was the wall we were stuck on longest. Every DB test errored with this. We
tried several wrong fixes:
- Tried `NullPool` (don't reuse connections) — helped but didn't solve it.
- Tried a sync cleanup fixture with `asyncio.run()` — **made it worse** (see Wall 4).
- Tried not closing connections at all — **caused a deadlock** (see Wall 4).

I was guessing instead of reading. The user told me to slow down and actually
look. That was the right call.

**The actual root cause was ONE line in `pytest.ini`:**
```ini
asyncio_default_fixture_loop_scope = session     # fixtures run in loop A
# (tests default to function scope)              # tests run in loop B
```
So the `db` fixture created the session in **loop A** (session-wide), but each
test ran in **loop B** (its own per-function loop). The session's connection,
born in A, was used in B → "different loop" crash.

The giveaway: **a single test passed, multiple tests failed.** That pattern
(`pytest tests/test_x::one_test` works, the full run doesn't) almost always means
*shared state / shared loop across tests*.

**Fix:** delete that line so fixtures and tests use the **same** (function-scoped)
loop:
```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

**Lesson:** in async tests, the fixture loop scope and the test loop scope MUST
match. A mismatch is invisible until you run more than one test.

### Wall 4 — the deadlock (a wrong fix I made)

While stuck on Wall 3, I "fixed" it by not closing DB connections in teardown.
That caused tests to **hang forever**. Why?

- Test opens a connection, holds a row lock (uncommitted/unclosed).
- Cleanup tries `TRUNCATE ... CASCADE` from a *different* connection.
- `TRUNCATE` needs an exclusive lock → waits for the first connection to release →
  it never does (I stopped closing it) → **deadlock**, hang forever.

**Lesson:** never "fix" a resource error by leaking the resource. The hang was a
clue pointing straight back at the unclosed connection.

### The final, correct design

```python
@pytest_asyncio.fixture
async def db(setup_database):
    eng = make_engine()                       # fresh NullPool engine per test
    session_factory = async_sessionmaker(eng, expire_on_commit=False)
    session = session_factory()
    try:
        yield session                         # the test runs here
    finally:
        # cleanup runs in the SAME loop as the test (no cross-loop crash)
        await session.rollback()
        await session.execute(text(
            "TRUNCATE spans, replays, traces, api_keys, projects CASCADE"))
        await session.commit()
        await session.close()                 # release locks (no deadlock)
        await eng.dispose()
```

Three ideas working together:
1. **Fresh engine per test (NullPool)** → no connection survives to a later loop.
2. **Cleanup inside the fixture's own loop** → no "different loop" error.
3. **Close the session before truncating completes** → locks released, no deadlock.

### Wall 5 — background tasks in API tests

`POST /v1/replays` kicks off `_run_replay` as a FastAPI **BackgroundTask**. In the
test, that background task ran against the app's *real pooled* engine (not our
NullPool one), and that pooled connection leaked into the next test's loop →
"different loop" again, but only for the replay API tests.

**Fix (also better test design):** API-layer tests should test the *endpoint's
contract* (did it create the rows, return 201?), NOT the background work. The
background work is tested separately in dedicated `_run_replay` engine tests. So
we mock the background task out in the API tests:
```python
with patch("app.routers.replays._run_replay", new=AsyncMock()):
    resp = await client.post("/v1/replays", json={...})
```

**Lesson:** unit-test the endpoint and the background job *separately*. Don't let
a fire-and-forget task run inside an endpoint test — mock it, test it on its own.

---

## How we test the replay engine without calling real Groq

The engine tests must exercise real DB logic but must NOT hit the paid Groq API.
We mock only the network call:
```python
with patch("app.routers.replays._call_groq",
           new=AsyncMock(return_value={
               "choices": [{"message": {"content": '{"label": "feature"}'}}],
               "usage": {"prompt_tokens": 120, "completion_tokens": 30},
           })):
    await _run_replay(...)
```
Everything else (reading the original trace, writing the new trace + spans,
computing token deltas) runs for real against Postgres. **Mock the boundary
(the external API), test everything inside it for real.**

---

## The final shape of the suite

```
server/tests/
├── conftest.py        # the hard-won fixtures: engine, db, client, factories
├── test_health.py     # 2  — endpoint + public access
├── test_traces.py     # 17 — ingest/list/get, idempotency, pagination,
│                       #      auth 401, project isolation
└── test_replays.py    # 25 — pure helpers, API endpoints, _run_replay engine
```
44 tests, run twice to prove no cross-test contamination. Wired into CI with a
real Postgres service container.

---

## Likely interview questions

**Q: How do you test async database code?**
Real Postgres test DB (not SQLite — you want JSONB/UUID to behave like prod).
Each test gets a fresh NullPool engine and a session; cleanup (TRUNCATE CASCADE)
runs inside the test's own event loop. The key constraint is that an asyncpg
connection is bound to its creating event loop, so fixture loop scope and test
loop scope must match.

**Q: You added a column and existing features broke. What happened?**
Adding `branched_from_span_id` created a second FK path between two tables, making
the `Trace.spans` relationship ambiguous — SQLAlchemy couldn't pick a join. Fixed
by specifying `foreign_keys` explicitly. The lesson is that a second FK between
two tables makes every relationship between them ambiguous.

**Q: A test passes alone but fails in the full suite. How do you debug it?**
That pattern screams shared state across tests — a shared event loop, a shared
connection, or DB rows not cleaned between tests. In our case it was a fixture/test
event-loop scope mismatch. I'd isolate by running pairs of tests and checking
fixture scopes and teardown.

**Q: Your tests hung forever once. Why?**
A deadlock: a test held a row lock on an unclosed connection, and cleanup's
TRUNCATE waited forever for that lock. Fixed by properly closing the session
before cleanup. A hang in DB tests is almost always a lock someone forgot to
release.

**Q: How do you test an endpoint that triggers a background job?**
Mock the background job in the endpoint test (assert the endpoint's synchronous
contract only), and test the job separately with its external calls mocked. Don't
let real background work run inside an endpoint test.

**Q: How do you avoid hitting paid APIs (Groq/OpenAI) in tests?**
Mock at the network boundary — patch the `_call_groq` function to return a canned
response. Everything inside (DB writes, token math) runs for real; only the
external HTTP call is faked.

---

## One-liner to remember

**An asyncpg connection belongs to the event loop that created it — match your
fixture and test loop scopes, clean up in-loop, and always release your locks.**
