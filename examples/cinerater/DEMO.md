# CineRater — Branch & Replay demo scenarios

Three scripted test cases that **prove** an upstream change re-executes
downstream correctly. Run [`demo_scenarios.py`](./demo_scenarios.py); it lands
linked traces in the dashboard and prints a diff URL for each.

CineRater is a 4-step agent:

```
parse query (LLM)  →  search_movies (tool)  →  get_movie_details (tool)  →  write recommendation (LLM)
      ▲ routing decision           ▲ downstream depends on the decision above
```

## The two levers

| | What changes | Mechanism | Shows |
|---|---|---|---|
| **Branch** | a span's **content** (output) | SDK-side replay (`loupe.replay`) — real tools re-run | upstream edit → downstream re-executes |
| **Replay** | the **query / instruction** | server `POST /v1/replays` — LLM re-runs, tools frozen | new prompt → new answer |

### Why we branch the *parse LLM span*, not the search tool

Provider LLM spans (and `@loupe.span`-decorated functions) **short-circuit** in
replay: the edited output is returned and flows downstream. A `loupe.span()`
context-manager block (like `search_movies`) still runs its body, so editing it
only changes what's *recorded*, not what flows on. The parse span is the real
upstream lever — editing its filters makes the live `search_movies` call re-run
with the new value.

> This is exactly why the dashboard now hides "Branch from here" on terminal
> spans: editing the final answer's output changes nothing downstream.

## The scenarios

- **A · Genre re-route** — original parses `{genre: "Sci-Fi"}`; we edit it to
  `{genre: "Romance"}`. `search_movies` re-runs for Romance and the final pick
  becomes a romance film. *(Verified: branched `search_movies` returned only
  Romance titles; final rec = "Past Lives", a romance.)*
- **B · Tighten the filter** — original parses `{genre: "Thriller"}`; we add
  `min_rating: 8.5`. Search narrows to top-rated thrillers → a different pick.
- **C · Change the instruction (replay)** — override the *write* system prompt
  to "one terse sentence, title + year only" and re-run the LLM steps. Same
  tools, terser answer.

## Run it

Server + dashboard must be up. Point at your **local** server with a key that's
valid against your **local** DB:

```bash
# from the repo root
set -a && source examples/cinerater/.env && set +a      # GROQ key, model
export LOUPE_HOST="http://localhost:8000"                # local server, not Render
export LOUPE_API_KEY=$(grep LOUPE_API_KEY dashboard/.env.local | cut -d= -f2)
export LOUPE_DASHBOARD="http://localhost:3000"

sdk/.venv/bin/python -m examples.cinerater.demo_scenarios
```

> ⚠️ **Env gotcha:** `examples/cinerater/.env` ships with `LOUPE_HOST` pointing
> at the live Render server and a key for *that* deployment. To see traces in
> your local dashboard, override `LOUPE_HOST` + `LOUPE_API_KEY` as above (the
> exported values win — `load_dotenv` doesn't override existing env vars).

Open each printed **DIFF** link to watch the change propagate.
