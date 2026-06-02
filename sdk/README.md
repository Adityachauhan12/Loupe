# loupe-sdk

Python SDK for [Loupe](https://github.com/Adityachauhan12/Loupe) — open-source observability and replay for LLM agents.

Instrument your agent with three lines, see every trace in the dashboard, then replay any run with a different prompt or model and diff the outputs side-by-side.

## Install

```bash
pip install loupe-sdk
```

## Quick start

```python
import loupe
from groq import Groq

loupe.init(api_key="lp_...", host="https://your-loupe-server.onrender.com")

client = Groq(api_key="...")
loupe.instrument_groq(client)          # also: instrument_openai, instrument_anthropic

@loupe.trace(name="my_agent")
def run_agent(query: str) -> str:
    with loupe.span("search", type="tool") as s:
        results = do_search(query)
        s.output = {"count": len(results)}
    ...
```

Every decorated call becomes a trace; every `loupe.span()` and auto-instrumented LLM call becomes a span under it.

## Self-host

See the [Loupe repo](https://github.com/Adityachauhan12/Loupe) for the full server + dashboard setup.
