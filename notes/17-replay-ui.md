# 17 — Dashboard: Replay UI

## What changed

**Server:**
- `server/app/routers/replays.py` — new router with `POST /v1/replays` and `GET /v1/replays/{id}`
- `server/app/schemas.py` — added `ReplayIn` and `ReplayCreated`
- `server/app/config.py` — added `openai_api_key` and `anthropic_api_key` settings
- `server/requirements.txt` — added `httpx` (for direct LLM API calls from server)
- `server/app/main.py` — registered replay router

**Dashboard:**
- `dashboard/components/ReplayForm.tsx` — Client Component: textarea for prompt override, dropdown for model (10 options across OpenAI/Anthropic/Groq)
- `dashboard/app/traces/[id]/actions.ts` — Server Action: proxies form to server, redirects to new trace on success
- `dashboard/app/traces/[id]/page.tsx` — added replay section below span tree (hidden for replay traces)

## How replay works (simple explanation)

Imagine your agent ran and gave a wrong answer. The trace is saved. You open it in Loupe and think "what if I gave it a different system prompt?"

1. You fill in the new prompt in the text box
2. Click "Run Replay →"
3. Server creates a new trace immediately (status = "running") and returns its ID
4. Server Action redirects you to that new trace page right away
5. In the background, server finds all LLM spans in the original trace, calls the LLM again with your new prompt, records the outputs
6. You refresh — trace shows "success" with the new LLM responses

**Analogy:** Like git stash + git apply. You "apply" a different prompt on top of the same input, without rerunning the whole agent.

## Sub-step learnings

### FK constraint ordering — two commits needed

The `replays` table has a FK: `new_trace_id → traces.id`. PostgreSQL checks FKs **immediately** (not at transaction end). So you can't INSERT into `replays` referencing a `traces` row that only exists in the same uncommitted transaction.

**Wrong (single commit):**
```python
db.add(new_trace)    # trace not yet in DB
db.add(replay_row)   # FK check fires now → FAIL
await db.commit()
```

**Correct (two commits):**
```python
db.add(new_trace)
await db.commit()    # trace now committed
db.add(replay_row)   # FK check now passes
await db.commit()
```

This is called "deferred FK constraint" in SQL — you can make it deferred at the schema level (`DEFERRABLE INITIALLY DEFERRED`) which would let both inserts happen in one transaction. For MVP, two commits is simpler and correct.

### Provider detection with model override

When user overrides model (e.g., original is `claude-sonnet-4-5`, override is `gpt-4o-mini`):
- You must call OpenAI, not Anthropic
- But `orig_span.provider = "anthropic"` — if you check that, you'd call Anthropic with a GPT model name → 400

**Fix:** When a model override is given, derive the provider from the **new model name**, not the original span's provider:

```python
if model_override:
    use_anthropic = model_override.startswith("claude")
else:
    use_anthropic = _is_anthropic(orig_span.provider, orig_span.model)
```

### BackgroundTasks need their own DB session

FastAPI's BackgroundTask runs after the response is sent. By then, the route handler's `AsyncSession` (from `Depends(get_db)`) is already closed. If you try to use it in the background task, you'll get "Session is already closed" errors.

**Fix:** Open a fresh session inside the background task:
```python
async def _run_replay(...):
    async with SessionLocal() as db:   # fresh session, not injected
        ...
```

`SessionLocal` is the `async_sessionmaker` object from `db.py`. Import and call it directly.

### Server Action pattern (no NEXT_PUBLIC needed)

The form's submit action is a Next.js **Server Action** — a function marked `"use server"` that runs on the Next.js server, not the browser. This means:
- `LOUPE_API_KEY` never touches the browser (it's read server-side only)
- No API route needed — the function IS the endpoint
- Works natively with `<form action={formAction}>` and `useActionState`

**Without Server Action:** you'd need `NEXT_PUBLIC_LOUPE_API_KEY` in the form's fetch call — that leaks the key to anyone who inspects network traffic.

### `useActionState` for form pending state

`useActionState` is React 19's hook for form actions. It gives you:
- `state` — whatever the action returned last
- `formAction` — pass this to `<form action={formAction}>`
- `isPending` — true while the action is running → disable submit button + show "Submitting..."

```typescript
const [state, formAction, isPending] = useActionState(myServerAction, initialState)
```

Note: `redirect()` from `next/navigation` throws a special error internally. You MUST re-throw it in a `catch` block, otherwise the redirect is swallowed:

```typescript
try {
  await boundAction(formData)
} catch (err) {
  if (err instanceof Error && err.message.includes("NEXT_REDIRECT")) throw err
  return { error: err.message }
}
```

## Interview questions this covers

**Q: How does replay work without re-running the user's agent code?**
A: For MVP, we replay only LLM spans. The server extracts the messages from each LLM span's input (which was captured by the SDK at instrumentation time), applies the overrides, and calls the LLM API directly. Tool spans are copied from the original. This works because the SDK captures exact inputs. The limitation: tool outputs aren't re-executed (you'd get the same tool results as the original).

**Q: What's the difference between a Server Action and an API Route Handler in Next.js?**
A: Both run server-side. Route Handlers (`app/api/route.ts`) are HTTP endpoints you call explicitly. Server Actions are functions called directly from the component tree — Next.js handles the HTTP transport internally. For forms, Server Actions are cleaner: no manual fetch, built-in loading state via `useActionState`, and no extra endpoint to maintain.

**Q: Why does the replay route return immediately instead of waiting for the LLM?**
A: LLM calls can take 5-30 seconds. If the endpoint blocked, the HTTP connection would time out on the client side, and the user would see an error. By returning immediately with the new trace ID and running the LLM call in a BackgroundTask, the user is redirected to the new trace page instantly. They see `status: running` and can refresh to see the result. (In v2, we'd use polling or SSE to auto-update the page.)

**Q: What happens if the BackgroundTask fails halfway through (server restarts)?**
A: The replay trace stays at `status: running` forever — orphaned. For MVP this is acceptable. The fix: a periodic cleanup job that marks stale `running` traces as `error` after N minutes. Or use a proper task queue (Celery + Redis) with retry semantics and persistent state.
