# Changelog

All notable changes to `loupe-sdk`. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/spec/v2.0.0.html).

## [0.3.3] — 2026-09-21

### Added

- **LLM spans now record *why* a completion ended**, in span metadata, whenever that is
  not the boring answer: `finish_reason`, `empty_answer`, and `reasoning_chars`.

  The case this comes from: an app moved off a retired model onto a reasoning model and
  kept its old `max_tokens`. Reasoning models write a hidden reasoning pass before the
  answer and both are paid from the same budget, so the reasoning consumed all of it and
  the answer came back empty with `finish_reason="length"`. Nothing raised — the caller
  parsed the empty string, fell back to a default, and carried on with clean logs and a
  200 response. The only trace of it was a span whose output read `{"content": ""}`,
  which cannot tell a truncation from a refusal or a content filter.

  Measured on the real spans: 1,885 characters of reasoning and 0 of answer at
  `max_tokens=500`; 2,523 and 0 at 800. The span now says so directly:

  ```json
  {"finish_reason": "length", "empty_answer": true, "reasoning_chars": 2126}
  ```

  A completion that stopped normally with an answer records nothing, so ordinary spans
  do not grow a field nobody reads. A turn that chose a tool (`finish_reason`
  `tool_calls`) is not flagged either — returning no content is the whole shape of an
  agentic step. Anthropic's `stop_reason: "max_tokens"` is normalised to `"length"` so
  there is one vocabulary downstream. The reasoning *text* is never stored, only its
  length: it is long, often not meant to be shown, and would bloat every span for the one
  case where the size is the clue.

  Covers `instrument_openai`, `instrument_groq` and `instrument_anthropic`. The Loupe
  dashboard shows this as a "truncated" / "no answer — truncated" badge on the span.

## [0.3.2] — 2026-08-20

### Fixed

- **`@loupe.trace` and `@loupe.span` now work on `async def` functions.** Previously only
  plain and generator functions were special-cased, so an `async def` fell through to the
  sync wrapper: it called the function without awaiting it and closed the trace
  immediately. That produced four wrong values at once — the output was recorded as a
  coroutine repr (`<coroutine object run at 0x…>`), `duration_ms` was `0`, spans created
  inside the function were silently dropped, and **a raised exception was recorded as
  `status="success"`**. Async generators were affected the same way.

  If you trace async agents (FastAPI routes, async SDK clients), traces from 0.3.1 and
  earlier are unreliable and errors are under-reported. Upgrading fixes new traces; it
  does not repair traces already stored.

  The decorators now branch at decoration time across all four function kinds and return
  a wrapper of the matching kind, so `inspect.iscoroutinefunction()` still reports the
  truth — which is what FastAPI reads to decide whether to await a route or hand it to a
  threadpool.

- `loupe` CLI rejects invisible characters (U+2028 and friends) in `LOUPE_HOST` and
  `LOUPE_API_KEY`, which browsers can insert into a copied token.

### Known limitations

- The `@loupe.span` **decorator** does not support async *generator* tools; the replay
  freeze/edit path has no well-defined behaviour for a stream. Use the `loupe.span()`
  context manager for those.

## [0.3.1] — 2026-07-17

### Added

- `loupe suite create` / `run` / `diff` CLI for prompt regression suites.
- `@loupe.trace` support for generator functions — the trace stays open until the
  generator is exhausted, so spans created mid-stream (e.g. an SSE agent's tool loop) are
  captured.
- `instrument_openai(client, provider="groq")` — optional provider label, for Groq
  accessed through the OpenAI SDK. Captures `tool_calls` in span output.
- Branch replays are tagged with `replay_mode` so a server-side preview is distinguishable
  from a real SDK-side re-run.

### Fixed

- CLI strips stray whitespace and newlines from `LOUPE_HOST` and `LOUPE_API_KEY`. A
  trailing newline in an API key had been causing `httpx` to raise `LocalProtocolError`.

## [0.3.0] — 2026-06-16

### Added

- `loupe.replay()` — SDK-side deterministic replay. Re-runs a traced agent in your own
  process from a branch point with an edited span output: spans before the branch are
  frozen to their stored outputs, and everything after runs live against your real tools.
- `loupe replay` CLI wrapping the same primitive.

## [0.2.0] — 2026-06-08

### Added

- `loupe.span()` works as a decorator with automatic argument and return-value capture,
  in addition to its context-manager form.

### Fixed

- Capture-audit corrections across trace and span payloads.

## [0.1.0] — 2026-06-02

Initial release: `@loupe.trace`, `loupe.span()`, batched async flush with retry and an
`atexit` flush, and auto-instrumentation for OpenAI, Anthropic, and Groq.

[0.3.2]: https://pypi.org/project/loupe-sdk/0.3.2/
[0.3.1]: https://pypi.org/project/loupe-sdk/0.3.1/
[0.3.0]: https://pypi.org/project/loupe-sdk/0.3.0/
[0.2.0]: https://pypi.org/project/loupe-sdk/0.2.0/
[0.1.0]: https://pypi.org/project/loupe-sdk/0.1.0/
