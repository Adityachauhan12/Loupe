# Loupe — Demo Runbook

> A follow-along script for recording the killer demo and capturing README
> screenshots. Target length on camera: **~2–3 minutes**. Everything below is
> copy-paste; `[📸 SHOT n]` marks a screenshot to capture (mapped to README slots
> at the bottom).
>
> **The story:** an agent gives a weak answer → open Loupe → spot the span that
> went wrong → branch from it with an edit → the side-by-side diff shows the
> original vs the fixed run. *That loop is the whole pitch.*

---

## 0. One-time prep (before you hit record)

Use `python3.11` for everything. Three processes need to be up.

```bash
cd /Users/adityachauhan/Desktop/Loupe_Project

# 1. Postgres (port 5433)
docker compose up -d db

# 2. Server (port 8000) — keep this terminal open
cd server
SENTRY_DSN="" ENVIRONMENT=development python3.11 -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. Dashboard (port 3000) — new terminal, keep open
cd dashboard
npm run dev
```

Sanity check (new terminal):

```bash
curl -s http://localhost:8000/health      # → {"status":"ok"}
open http://localhost:3000                 # dashboard loads
```

Pull the keys you'll reuse below into shell vars:

```bash
cd /Users/adityachauhan/Desktop/Loupe_Project
LKEY=$(grep LOUPE_API_KEY dashboard/.env.local | cut -d= -f2 | tr -d '"' | tr -d ' ')
GKEY=$(grep '^GROQ_API_KEY' server/.env | cut -d= -f2 | tr -d '"' | tr -d ' ')
```

> Tip: run through the whole script once **without** recording to warm the Render
> cache / Next routes and confirm the data looks good, then record the second pass.

---

## 1. Create the trace to debug (off-camera or as the opener)

Run the instrumented example agent so there's a fresh, real trace:

```bash
LOUPE_HOST=http://localhost:8000 LOUPE_API_KEY="$LKEY" GROQ_API_KEY="$GKEY" \
  python3.11 -m examples.cinerater.agent "best heist movie"
```

Grab the new trace id + its first LLM span id (you'll branch this span):

```bash
TID=$(curl -s -H "X-API-Key: $LKEY" "http://127.0.0.1:8000/v1/traces?limit=1" \
  | python3.11 -c 'import sys,json;print(json.load(sys.stdin)["items"][0]["id"])')
SID=$(curl -s -H "X-API-Key: $LKEY" "http://127.0.0.1:8000/v1/traces/$TID" \
  | python3.11 -c 'import sys,json;t=json.load(sys.stdin);print([s for s in sorted(t["spans"],key=lambda x:x["started_at"]) if s["type"]=="llm"][0]["id"])')
echo "trace=$TID  first_llm_span=$SID"
```

---

## 2. On camera — the walkthrough

### Beat 1 — the traces list

Open `http://localhost:3000`.

- Narrate: *"Every agent run is one trace — status, duration, tokens, cost, at a glance."*
- **[📸 SHOT 1 — Traces list]**

### Beat 2 — the trace detail (spot the bug)

Click into the `cinerater` trace (or open `http://localhost:3000/traces/$TID`).

- Narrate: *"Here's the full span tree — the LLM parse, the tool calls, the final write-up. This first LLM step parsed the query into a genre — say it picked the wrong one, and the recommendation downstream is weak."*
- Expand the first `llm` span to show its output.
- **[📸 SHOT 2 — Trace detail / span tree]**

### Beat 3 — branch from the bad span

You have **two** ways to branch. Pick one for the video:

**Option A — dashboard one-click (most visual):**
- Expand the first `llm` span → click **"Branch from here"**.
- Note the honest helper text: *"Preview branch (LLM-only)… tools can't run on the server."*
- Edit the JSON output (e.g. change the genre), click **Continue**.
- Narrate: *"This is the quick preview — it re-runs the LLM but doesn't touch my real tools."*

**Option B — `loupe replay` (the true counterfactual, edit propagates):**
```bash
GROQ_API_KEY="$GKEY" python3.11 -m loupe.cli replay \
  --agent examples.cinerater.agent:recommend \
  --trace "$TID" --span "$SID" \
  --output '{"content": "{\"genre\": \"Sci-Fi\", \"year\": 2022}"}' \
  --api-key "$LKEY" --host http://localhost:8000
```
- Narrate: *"This runs in my process, so my real `search_movies` re-executes and the edit flows all the way to the final answer."*
- Copy the `branched trace created: <id>` it prints.

### Beat 4 — the payoff: side-by-side diff

Open the branched trace, then click **"View diff"** in the lineage banner
(or go to `http://localhost:3000/traces/<branched_id>/diff`).

- Narrate, pointing at the screen:
  - *"Left is the original, right is the branch — aligned from the branch point on."*
  - the **kind label** (SDK-side = edit propagated / Server-side = LLM-only preview)
  - the **Δ tokens / cost / latency** row
  - the **per-span outputs** side by side — the changed answer
  - if status flipped: the green **"✓ Branch fixed the run"** banner
- **[📸 SHOT 3 — Branch diff (the headline shot)]**

Close with: *"Production trace → branch → diff. A debugger for non-deterministic
agents."*

---

## 3. Screenshots → README slots

The current `docs/*.png` are from **before** the UI overhaul and have **no branch
diff**. Recapture with the new UI:

| README slot (`README.md` line ~27) | File to overwrite | Capture in |
|---|---|---|
| Traces list | `docs/traces-list.png` | SHOT 1 |
| Trace detail (span tree) | `docs/trace-detail.png` | SHOT 2 |
| Side-by-side diff | `docs/replay-diff.png` | SHOT 3 (use the **branch** diff) |

> Optional: also add a 4th image of the status-change banner if you stage an
> error→success branch. After dropping the PNGs, the README table renders them
> automatically — no code change. (Ask me to add a dedicated branch-diff row/caption
> if you want a 4-up table.)

---

## 4. Reset between takes

Delete the branch you created so the next take is clean (replace `<branched_id>`):

```bash
docker exec loupe-db psql -U loupe -d loupe -c \
  "DELETE FROM replays WHERE new_trace_id='<branched_id>'; DELETE FROM traces WHERE id='<branched_id>';"
```

(Original trace stays; re-run Beat 3 to branch again.)

---

## 5. Gotchas

- **Server serving stale code?** Restart uvicorn — a long-lived dev server keeps
  old bytecode (this bit us once; see [notes/26](notes/26-branch-diff-view.md)).
- **`loupe` not a global command** — use `python3.11 -m loupe.cli` (SDK runs from
  local source via the editable install).
- **Dashboard timestamps** are forced to IST (`Asia/Kolkata`).
- **Live (deployed) demo** instead of local: the URLs are in the README; Render's
  free tier sleeps ~15 min, so `curl <render-url>/health` first to wake it.
