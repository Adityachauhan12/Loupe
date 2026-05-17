# 13 — SDK: Groq Auto-Instrumentation

## What changed

- Created `sdk/loupe/integrations/groq.py` — patches `client.chat.completions.create` on the passed Groq instance.
- Exported `instrument_groq` from `sdk/loupe/__init__.py`.
- Added `sdk/tests/test_groq_integration.py` — 3 unit tests (cost estimation + span capture via mock).

## Why Groq was fast

Groq exposes an OpenAI-compatible API: same `client.chat.completions.create` signature, same response shape (`usage.prompt_tokens`, `usage.completion_tokens`, `choices[0].message.content`). The implementation is a copy of `openai.py` with three changes:
1. Span name: `"groq.chat"` instead of `"openai.chat"`
2. Provider field: `"groq"`
3. Pricing table: Groq's token rates (much cheaper than OpenAI — LLaMA 3 70B at $0.59/$0.79 vs GPT-4o at $2.50/$10.00)

## Sub-step learnings

### Monkey-patching an instance (not the class)

We patch `client.chat.completions.create` (the bound method on **this instance**), not `groq.Groq.chat.completions.create` (the class). This means:
- Only the passed client is affected — other clients in the same process are untouched.
- The user can instrument different clients with different providers side-by-side.
- `functools.wraps` preserves the original function's `__name__`, `__doc__`, and type hints so IDEs and introspection still work correctly.

### Why `functools.wraps` matters for patching

Without `@functools.wraps(original_create)`, tools like `inspect.signature()` and IDE autocomplete would see the wrapper's generic `(*args, **kwargs)` signature instead of the original. For an SDK that patches user code, preserving the original interface is important.

### Groq's pricing model

Groq prices are meaningfully lower than OpenAI because they run on LPU (Language Processing Unit) hardware, not GPUs. The cost table uses prefix matching (same as OpenAI/Anthropic integrations) so `"llama3-70b-8192"` matches the `"llama3-70b"` key. If a model isn't in the table, cost returns `None` rather than crashing — graceful degradation.

## Interview questions this covers

**Q: Why do you patch the instance rather than the class?**  
A: Avoids global side effects. Users may have multiple clients in the same process, or mix instrumented and uninstrumented calls. Instance-level patching gives the user control.

**Q: How would you extend this to support streaming responses?**  
A: Groq (like OpenAI) supports `stream=True`, which returns a generator of chunks rather than a single response. The current wrapper doesn't handle this — `response.usage` is `None` for streams. A production fix would detect `kwargs.get("stream")` and wrap the generator to aggregate tokens as chunks arrive, then record the span on the final chunk.

**Q: What happens if the user upgrades the Groq SDK and the method signature changes?**  
A: `functools.wraps` + `*args/**kwargs` forwarding means we don't bind to specific parameter names — we pass everything through unchanged. The only coupling is the response shape (`.usage`, `.choices`). We use `getattr(..., None)` throughout, so an unexpected shape silently records `None` fields rather than crashing.

**Q: How does cost estimation work and why might it be wrong?**  
A: Prefix matching against a hardcoded table. It can be wrong if: (1) Groq changes pricing, (2) a new model doesn't match any prefix, (3) the user passes a fine-tuned model name. For MVP this is fine — the note "approximate" is explicit. A production system would call Groq's pricing API or pull from a config file.
