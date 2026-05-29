# CineRater — Loupe SDK example

A tiny movie-recommendation agent instrumented with [Loupe](../../README.md).
Use it to verify a local Loupe install end-to-end: run the agent, then open
the dashboard and watch the trace appear with every LLM call and tool call
as a span underneath it.

## What the agent does

For a query like `"recommend a thriller from 2023"`:

1. **LLM** — parses the query into structured filters (`genre`, `year`, `min_rating`).
2. **Tool** — `search_movies(...)` filters a hardcoded catalogue of 25 movies.
3. **Tool** — `get_movie_details(...)` runs for the top 2 candidates.
4. **LLM** — writes the natural-language recommendation.

All four steps appear as spans inside a single trace named `cinerater`.

## Quickstart

From the **project root**:

```bash
# 1. Start Postgres + run migrations + start the server (see top-level README)
docker compose up -d
cd server && source .venv/bin/activate && alembic upgrade head
uvicorn app.main:app --reload --port 8000 &

# 2. Create a project + API key
cd server && python -m scripts.create_project cinerater
# → copy the printed `api_key` value

# 3. Install the SDK in editable mode + example deps
pip install -e ./sdk
pip install -r examples/cinerater/requirements.txt

# 4. Configure env
cp examples/cinerater/.env.example examples/cinerater/.env
# → fill in LOUPE_API_KEY and GROQ_API_KEY

# 5. Run
python -m examples.cinerater.agent "recommend a thriller from 2023"
```

Open <http://localhost:3000> — the run shows up at the top of the trace
list. Click into it to see the span tree, then hit **Replay** to try a
different prompt or swap the model.

## Files

- [data.py](data.py) — 25-movie catalogue, hardcoded
- [tools.py](tools.py) — `search_movies` and `get_movie_details`, wrapped as Loupe tool spans
- [agent.py](agent.py) — the agent: `@loupe.trace` entry point + two Groq LLM calls

## Why hardcoded data?

The demo needs to be reliable. A live API (TMDB etc.) adds a network
dependency and a second API key — both can break the screencast you'll
record for the README. Twenty-five movies is enough for the agent to make
non-trivial choices across genre, year, and rating.
