# 19 — Sentry + structlog

## What changed

- `server/requirements.txt` — added `sentry-sdk[fastapi]==2.60.0` and `structlog==25.5.0`
- `server/app/main.py` — Sentry init (only when `SENTRY_DSN` is set) + structlog configure
- `server/app/routers/replays.py` — replaced `logging.getLogger` with `structlog.get_logger()`, updated all log calls to key=value style

## What is Sentry? (simple)

Sentry ek error tracking tool hai. Jab bhi server crash ho ya exception aaye:

**Without Sentry:**
```
User ka request fail hua
Tu manually logs grep karta hai  
Kabhi root cause milta hai, kabhi nahi
```

**With Sentry:**
```
Email aaya: ❌ RuntimeError in _run_replay()
  File: replays.py line 187
  Error: "ANTHROPIC_API_KEY not configured"
  Users affected: 3
  First seen: 2:14 AM
  Full stack trace: [...]
```

Seedha error + file + line + stack trace. Bina kuch kiye.

## What is structlog? (simple)

`print()` ya `logging.warning("something happened")` ki jagah:

```python
logger.info("replay complete", replay_id="abc123", status="success", tokens=78)
```

Output dev mein colour-coded:
```
[2026-05-20T05:57:09Z] [info] replay complete  replay_id=abc123  status=success  tokens=78
```

Output production mein JSON:
```json
{"event": "replay complete", "replay_id": "abc123", "status": "success", "tokens": 78, "timestamp": "2026-05-20T05:57:09Z"}
```

JSON logs grep-able hain: "find all failed replays" = ek command.

## Sub-step learnings

### Sentry init only when DSN is set

Sentry DSN ek secret URL hai — agar set nahi hai (dev mein), Sentry simply off rehta hai. Tujhe dev mein kuch configure nahi karna:

```python
if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, ...)
```

`sentry-sdk[fastapi]` bracket notation ek "extra" install karta hai — FastAPI + Starlette specific integrations. Ye automatically:
- Unhandled exceptions capture karta hai
- Request path, method, status code attach karta hai  
- User IP / request ID add karta hai
- `traces_sample_rate=0.1` = 10% requests ka performance trace (latency breakdown)

### structlog processors — pipeline pattern

structlog ka architecture ek pipeline hai. Har log event processors ki chain se guzarta hai:

```
logger.info("event", key=val)
         ↓
merge_contextvars   ← thread-local context add karo (e.g. request_id)
         ↓
add_log_level       ← "level": "info" add karo
         ↓
TimeStamper         ← "timestamp": "2026-..." add karo
         ↓
ConsoleRenderer     ← human-readable output (dev)
OR JSONRenderer     ← {"event": ..., "level": ...} (production)
```

Processor = function that takes event_dict, returns event_dict. Isse custom processors add karna easy hai — e.g. "add trace_id to every log event from this request."

### `add_logger_name` processor — stdlib only

`structlog.stdlib.add_logger_name` sirf stdlib loggers ke saath kaam karta hai (jinke paas `.name` attribute hota hai). `PrintLoggerFactory` ke `PrintLogger` objects ke paas `.name` nahi hota → `AttributeError`.

Fix: is processor ko remove kar do. Logger name generally needed nahi hota jab sab logs ek hi app se aa rahe hain.

**Rule:** structlog ke stdlib processors (jo `structlog.stdlib.*` mein hain) sirf tab use karo jab `logger_factory=structlog.stdlib.LoggerFactory()` use kar rahe ho. `PrintLoggerFactory` ke saath sirf native processors use karo.

### Structured logs vs unstructured logs — why it matters

Unstructured:
```
replay abc123 complete — status=success
replay def456 complete — status=error
```

To find all errors: `grep "status=error"` — works but fragile, parsing text.

Structured (JSON):
```json
{"event": "replay complete", "replay_id": "abc123", "status": "success"}
{"event": "replay complete", "replay_id": "def456", "status": "error"}
```

To find all errors: `jq 'select(.status == "error")' logs.json` — precise, reliable.
To find avg tokens per successful replay: 2-line jq command.
To send to Datadog/Grafana/Splunk: direct JSON ingestion, no parsing needed.

### `send_default_pii=False`

Sentry by default user IP address, cookies, request bodies capture kar sakta hai — jo GDPR violation ho sakta hai. `send_default_pii=False` ye off kar deta hai. Always set this.

## How to set up Sentry (for when you deploy)

1. Go to sentry.io → Create free account
2. New Project → Python → FastAPI
3. Copy the DSN (looks like `https://abc123@o123456.ingest.sentry.io/789`)
4. Add to `server/.env`: `SENTRY_DSN=https://abc123@...`
5. Restart server — done. All unhandled exceptions now appear in Sentry dashboard.

## Interview questions

**Q: What's the difference between Sentry and logs?**
A: Logs are passive — you have to know something went wrong and go look. Sentry is active — it tells you when something breaks, with full context (stack trace, request, user). Logs are for debugging after you know there's a problem. Sentry is for knowing there's a problem in the first place.

**Q: Why structured logging instead of print/logging.info?**
A: Structured logs (JSON key-value) are machine-parseable. You can query them like a database — "find all requests where tokens > 1000 and status = error". Plain text logs require regex parsing which is fragile. At scale (millions of log lines), structured logs are the only practical option.

**Q: Why `traces_sample_rate=0.1` and not 1.0?**
A: Performance tracing (tracking how long each function takes) creates overhead and generates a lot of data. 10% sampling means 1 in 10 requests is fully traced — enough to identify performance bottlenecks without 10x the cost and storage. Error tracking is always 100% (no sampling) — you want to know about every error.

**Q: What does `sentry-sdk[fastapi]` install that plain `sentry-sdk` doesn't?**
A: The `[fastapi]` extra installs `FastApiIntegration` and `StarletteIntegration`. These hook into FastAPI's request lifecycle to automatically:
- Capture the HTTP method, path, status code with each error
- Set Sentry transaction names (e.g. "GET /v1/traces/{trace_id}")
- Propagate trace context across async tasks

Without these integrations, Sentry still captures exceptions but without the HTTP request context.
