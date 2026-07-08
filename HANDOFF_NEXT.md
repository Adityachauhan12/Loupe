# Loupe — Session Handoff (v2.2 shipped → what's next)

> Paste this file's path into the new chat and say the first message in §9.
> Written 2026-07-08. Repo on `main`, fully pushed (head `542aa5a`). SDK `0.3.0` live on PyPI.

---

## 1. What Loupe is (30-second version)

Loupe = observability + **replay/branch debugger + prompt regression testing** for LLM
agents. MVP live (SDK on PyPI, dashboard on Vercel, server on Render, Postgres on Neon).

Three layers now exist:
- **Observe** (MVP): instrument an agent, see every trace/span.
- **Replay/branch** (v2.1): open a failed trace → edit a span → re-run from there →
  side-by-side diff of original vs counterfactual.
- **Prompt CI/CD** (v2.2, **just shipped**): golden suites of saved traces → replay each
  against a new prompt → LLM judge scores each → GitHub Action blocks PRs on regressions.

Full spec: [CLAUDE.md](CLAUDE.md). Every decision + rationale:
[ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md). Plain-language explainer of the whole
system (capture, replay, security, v2.2): [docs/concepts-explained.md](docs/concepts-explained.md).

---

## 2. How the user likes to work (IMPORTANT — match this)

- **Teach as you build:** narrate steps in plain language, drop learnings, surface interview
  Q&A. This is a **portfolio/learning** sprint. The user writes in **Hinglish** — answer in the
  same simple style with small analogies.
- **One sub-step at a time. Test rigorously as you go** (tests *with* the code). Confirm before
  moving on. Use a **TodoWrite** list.
- Be **direct and honest** — flag limitations out loud (the best features came from that).
- For architectural decisions: lay out *tension → options → tradeoffs → recommendation →
  "decision needed"*, get the user's pick, record it in ARCHITECTURE_DECISIONS.md, then build.
- After meaningful work: write a **`notes/NN-*.md`** file, update `notes/README.md`, **commit**.
- Commit straight to **`main`**. Commit footer:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. **Push only when asked.**
- **Cost constraint (load-bearing):** the user runs on a small API credit and does **not** want
  to spend on Claude for dev/demo. The judge defaults to **free Groq/Llama**; Claude Sonnet is
  opt-in. Keep new work zero-cost by default.

---

## 3. What's DONE (don't rebuild)

**v2.1 Time-Travel Debug** — branch/replay engine, `POST /v1/traces/{id}/branch`, SDK-side
`loupe.replay` (edit propagates through real tools) vs server-side branch (LLM-only preview),
branch-vs-original diff view. Decisions B1–B7.

**v2.2 Prompt CI/CD** — shipped in 6 commits (`8cc17c7`..`542aa5a`):
| Piece | Where |
|---|---|
| DB: `suites`, `suite_traces`, `suite_runs` (migration `e5b2d9c4a7f1`) | [server/app/models.py](server/app/models.py) |
| `JudgeService` — hybrid (free deterministic pre-check + LLM judge), pluggable backend | [server/app/services/judge.py](server/app/services/judge.py) |
| Endpoints: `POST /v1/suites`, `GET /v1/suites[/{id}]`, `POST /v1/suites/{id}/run` (async→202), `GET /v1/suite_runs/{id}` | [server/app/routers/suites.py](server/app/routers/suites.py) |
| CLI: `loupe suite create/run/diff` (exit 1 on regression = CI gate) | [sdk/loupe/cli.py](sdk/loupe/cli.py) |
| Composite GitHub Action + demo | [loupe-action/](loupe-action/), [examples/prompt-ci-demo/](examples/prompt-ci-demo/) |
| Design B8.1–B8.5 + notes | [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md), [notes/27-v2.2-prompt-cicd.md](notes/27-v2.2-prompt-cicd.md) |

**SDK `0.3.0` published to PyPI** — includes the `suite` CLI + the CineRater-integration
changes (generator-function `@trace` support for SSE agents, `instrument_openai(provider=...)`,
tool-call capture, token/cost rollup). The **real CineRater Django app** at `~/Desktop/CineRater`
is now the primary demo source (see `claude.md` → "Real CineRater Integration"); `examples/cinerater/`
is the legacy toy for the self-contained quickstart.

**Tests green: server 88, SDK 41.**

### Key design decisions to know (v2.2)
- **B8.1** suites store trace IDs by reference (join table), not copies.
- **B8.2** `suite_runs.results` = one JSONB column (read as a whole).
- **B8.3** global default rubric + optional per-suite override.
- **B8.4** hybrid scoring (deterministic pre-check skips the LLM on identical outputs);
  **pluggable judge backend, default free Groq/Llama, Claude opt-in.**
- **B8.5** composite Action (wraps the CLI); **zero-tolerance gate** (any regression blocks;
  no confidence gating — deliberately).

---

## 4. What's NEXT (pick with the user)

Nothing is blocking; these are the open threads, roughly by value:

1. **Live GitHub demo (Track D, highest portfolio value).** Wire the real PR-blocking flow:
   seed traces on the deployed Render Loupe → `loupe suite create --from last:15` → set repo
   secrets (`LOUPE_HOST`, `LOUPE_API_KEY`) + var (`LOUPE_SUITE_ID`) → open a PR that breaks
   the prompt → screenshot the red check + PR comment. Runbook already written:
   [examples/prompt-ci-demo/README.md](examples/prompt-ci-demo/README.md). GitHub-hosted
   runners can't reach localhost → must use the deployed instance. Free Groq judge + ~15-trace
   suite ≈ $0.
2. **B11 — PII/secret redaction (tracked, not built).** Capture is shape-agnostic, so a secret
   in a tool arg/prompt is stored plaintext *and* shipped to the judge (a third party). Design:
   SDK-side redaction before serialization (key denylist + value regex, on by default,
   `loupe.init(redact_keys=[...])`) + scrub before the judge. Full write-up: ARCHITECTURE_DECISIONS.md B11.
3. **CLAUDE.md v2.2 checklist tick-off** — mark the v2.2 build items `[x]` (skipped this session
   because `claude.md` had uncommitted WIP at the time; it's clean now).
4. **Track D leftovers** — killer-demo recording, real README screenshots (replace `docs/*.png`).
5. **Optional polish** — separate public demo repo (more authentic screenshot), a TS action
   (resume bullet only), `--max-regressions` knob, auto-detect changed prompt files.

---

## 5. Environment & gotchas (saves the new chat real time)

- **Python: `python3.11`** for everything (pip, pytest, alembic, uvicorn). `alembic` isn't on
  PATH → `python3.11 -m alembic`.
- **Local Postgres:** `docker compose up -d db` (service `db`, container `loupe-db`, port
  **5433**). DBs: `loupe` (dev), `loupe_test` (tests). DBeaver connects at
  `localhost:5433`, db `loupe`, user/pass `loupe`/`loupe`.
- **Run server:** from `server/`,
  `SENTRY_DSN="" ENVIRONMENT=development python3.11 -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
- **Server tests:** from `server/`, `SENTRY_DSN="" python3.11 -m pytest tests/ --timeout=30 -q` → **88**.
  (conftest `drop_all`+`create_all`, so new tables/columns don't silently break the suite.)
- **SDK tests:** from `sdk/`, `python3.11 -m pytest tests/ -q` → **41**.
- **Fast DB peek:** `docker exec loupe-db psql -U loupe -d loupe -c "\dt"` (or `\d suite_runs`,
  `SELECT * FROM suites;`) — faster than any GUI.
- **JudgeService keys:** free Groq path needs `GROQ_API_KEY` in `server/.env`; Claude path needs
  `ANTHROPIC_API_KEY`. Suite backend override: `--backend claude/claude-sonnet-4-6`.
- **⚠️ Stale-server trap:** a long-lived `uvicorn` serves **old code**. When behaviour
  contradicts the source, **restart the server** before deep-diving.
- **⚠️ Bash CWD persists** between tool calls — `git`/`pytest` paths broke twice this session
  because CWD was `server/` or `sdk/`. `cd` to repo root for `git`.
- **PyPI publish:** `cd sdk && python3.11 -m build && python3.11 -m twine upload dist/*`
  (user enters the token — irreversible, their credential). Bump `version` in
  `sdk/pyproject.toml` first. `loupe` console script = `loupe.cli:main`.
- **Render free tier sleeps** (~15 min) — wake with `curl <render-url>/health`.

---

## 6. Quick file map (v2.2)

- `server/app/models.py` — `Suite` / `SuiteTrace` / `SuiteRun` ORM (+ existing Trace/Span).
- `server/app/routers/suites.py` — endpoints + `_run_suite` (reuses `replays._run_replay` per
  trace, then `judge_service.judge`).
- `server/app/services/judge.py` — `judge()`, `deterministic_check()`, `parse_backend()`,
  `DEFAULT_RUBRIC`, provider calls (Groq JSON mode / Anthropic `output_config.format`).
- `server/app/config.py` — `judge_backend` default (`groq/llama-3.3-70b-versatile`).
- `sdk/loupe/cli.py` — `loupe suite create/run/diff` + the v2.1 `replay` command.
- `loupe-action/action.yml` — composite Action. `examples/prompt-ci-demo/` — demo + runbook.
- `notes/27-v2.2-prompt-cicd.md` — the v2.2 build note.
- **⚠️ When writing Claude/Anthropic code, invoke the `claude-api` skill first** — the API
  drifted (adaptive thinking, `output_config.format`, no `budget_tokens`); don't write from memory.

---

## 7. Loose ends noted this session

- Two untracked screenshots at repo root (`Screenshot 2026-07-01 …png`) — the user's, left alone.
- `docs/*.png` are still placeholder-ish (Track D leftover).

---

## 8. First message to send in the new chat

> "Read HANDOFF_NEXT.md and continue. v2.2 Prompt CI/CD is shipped (SDK 0.3.0 on PyPI). Let's
> do the **live GitHub demo** next — seed traces on the deployed Loupe, create a golden suite,
> wire the loupe-action into a repo, and land a real PR that shows the red check + comment.
> Teach as you build, one sub-step at a time, test rigorously, Hinglish, and keep it zero-cost
> (free Groq judge)."
>
> *(Or swap the goal for: B11 redaction · CLAUDE.md checklist tick-off · Track D screenshots.)*
