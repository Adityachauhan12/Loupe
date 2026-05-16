# Items 11–12 — SDK: OpenAI and Anthropic auto-instrumentation

Auto-instrumentation means the user calls one function at startup, and every LLM call after that is automatically recorded — no `with loupe.span()` needed for LLM calls.

---

## What changed

- `sdk/loupe/integrations/openai.py` — `instrument_openai(client)` patches `client.chat.completions.create`
- `sdk/loupe/integrations/anthropic.py` — `instrument_anthropic(client)` patches `client.messages.create`
- `loupe/__init__.py` — exports both
- Fixed a bug in `core.py`: span error handler used `type.__class__.__name__` (gives `"str"`, the type of the `type` parameter) instead of `exc.__class__.__name__`

---

## How the patching works

```python
original_create = client.chat.completions.create

def patched_create(*args, **kwargs):
    with loupe.span("openai.chat", type="llm") as s:
        s.input = {"messages": kwargs.get("messages")}
        response = original_create(*args, **kwargs)   # the real call
        s.prompt_tokens = response.usage.prompt_tokens
        s.output = {"content": response.choices[0].message.content}
    return response

client.chat.completions.create = patched_create
```

The original method is saved, wrapped, and replaced on the instance. Every call goes through the wrapper transparently.

---

## Learnings

- **Monkey-patching on the instance, not the class.** We replace the method on the specific `client` object passed in, not on `openai.OpenAI` globally. This means other code that creates its own OpenAI client is unaffected. It's opt-in and scoped. Global class patching (what OpenTelemetry does) is more powerful but has more surface area for unexpected interactions.
- **Don't import the library in the instrumentation module.** `instrument_openai(client)` receives the client object — it doesn't need to `import openai`. Removing the guard means the SDK works with any OpenAI-compatible client (e.g. Azure OpenAI, local LLM servers with OpenAI-compatible APIs) and doesn't require openai to be installed as a transitive dep.
- **`getattr(obj, "field", None)` instead of `obj.field`.** LLM provider SDKs change their response shapes between versions. Using `getattr` with a fallback means the instrumentation doesn't crash if a field moves or disappears — it just records `None`.
- **Cost estimation is approximate.** The lookup table uses model name prefixes. Prices change; treat costs as directional signals, not accounting. For production use you'd pull from a pricing API or let the user configure it.
- **Tokens from Anthropic vs OpenAI differ in naming.** OpenAI: `usage.prompt_tokens` / `usage.completion_tokens`. Anthropic: `usage.input_tokens` / `usage.output_tokens`. The integration layer normalises these to Loupe's `prompt_tokens` / `completion_tokens` so the dashboard sees a consistent schema.

**Interview questions**

1. What's the difference between patching a class method globally vs patching an instance method? *(global = affects all instances past and future; instance = scoped, opt-in, no surprise side effects on other clients)*
2. Why would you use `getattr(obj, "field", None)` when integrating with an external SDK? *(SDK response shapes change between versions; defensive access prevents instrumentation from crashing the user's app)*
3. Auto-instrumentation libraries (OpenTelemetry, Datadog APM) use global class patching. What's the tradeoff vs instance patching? *(global = zero-touch setup, catches everything; instance = explicit, predictable, harder to accidentally break)*
