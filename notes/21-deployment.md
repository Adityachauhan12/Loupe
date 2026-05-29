# 21 — Deployment: Neon + Render + Vercel

## What changed

- `server/start.sh` — `alembic upgrade head` + uvicorn, runs on every Render deploy
- `server/.python-version` — pins Python 3.13 for Render
- `render.yaml` — Render service definition (rootDir, build, start, env vars)

## Deployment order — why this order

```
Neon (DB) → Render (server) → create API key on server → Vercel (dashboard)
```

Each step depends on the previous:
- Render needs Neon's DATABASE_URL at startup
- Dashboard needs the Render URL + an API key that lives in the DB
- Can't create the API key until server is running and migrations have run

## Step 1 — Neon (Postgres)

1. Go to **neon.tech** → create account → New Project → name it `loupe`
2. Copy the **connection string** from "Connection Details" → "Prisma" (then swap `prisma://` for `postgresql+asyncpg://`)

Format needed:
```
postgresql+asyncpg://neondb_owner:PASS@ep-xxx-xxx.region.aws.neon.tech/neondb?ssl=require
```

Key difference from local: **`?ssl=require`** at the end. Neon requires TLS, asyncpg won't connect without it.

> *Interview Q:* Why `+asyncpg` in the URL? *(SQLAlchemy async engine needs an async DB driver. `asyncpg` is the standard choice for Postgres. The prefix tells SQLAlchemy which driver to load — `postgresql+asyncpg` vs `postgresql+psycopg2` for sync.)*

> *Interview Q:* Why Neon over a Render Postgres addon? *(Neon free tier is 512MB + unlimited time; Render's free Postgres expires after 90 days. Neon also gives branching — a separate DB branch per PR, useful for v2's Prompt CI/CD story.)*

## Step 2 — Render (FastAPI server)

1. **Push code to GitHub** if not already done
2. Go to **render.com** → New → "Blueprint" (uses `render.yaml`) → connect your repo
3. Render will detect `render.yaml` and show `loupe-server` service
4. Before deploying, click into the service env vars and set:
   - `DATABASE_URL` → paste Neon connection string (with `?ssl=require`)
   - `SENTRY_DSN` → your Sentry DSN
   - `GROQ_API_KEY` → your Groq key
   - `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` → optional, for replay model choice
5. Click **Deploy**

What happens on deploy:
```
1. pip install -r requirements.txt     ← build
2. alembic upgrade head                ← start.sh step 1, creates tables
3. uvicorn app.main:app --host 0.0.0.0 --port $PORT   ← start.sh step 2
```

After ~2 min, server is live at `https://loupe-server.onrender.com` (or similar).

**Verify:**
```bash
curl https://loupe-server.onrender.com/health
# → {"status": "ok"}
```

> *Interview Q:* Why run migrations in `start.sh` and not the build command? *(Build command runs without DATABASE_URL being available as a runtime secret on some platforms. `startCommand` always has access to all env vars. Also — if you run migrations at build time and the build is shared across instances, you might run migrations multiple times. Startup is cleaner.)*

> *Interview Q:* Why `exec uvicorn` not just `uvicorn`? *(`exec` replaces the shell process with uvicorn — uvicorn becomes PID 1. This means OS signals (SIGTERM for graceful shutdown) go directly to uvicorn instead of being swallowed by bash. Without `exec`, Render sends SIGTERM → bash exits → uvicorn gets SIGKILL, no graceful shutdown.)*

> *Interview Q:* Is `alembic upgrade head` in startup idempotent? *(Yes. Alembic checks `alembic_version` table first. If current revision = head, it's a no-op. Safe to run on every restart.)*

## Step 3 — Create API key on live server

SSH into Render shell (or use Render's "Shell" tab):
```bash
python -m scripts.create_project loupe-prod
# prints: project_id + api_key (lp_...)
```

**Save the raw `api_key` value.** It's printed once — we never store plaintext. Copy it for Step 4.

## Step 4 — Vercel (Next.js dashboard)

1. Go to **vercel.com** → New Project → import from GitHub
2. **Root Directory** → set to `dashboard` (Vercel won't auto-detect in a monorepo)
3. Framework: Next.js (auto-detected once root is `dashboard/`)
4. Environment Variables (add these):

| Key | Value |
|-----|-------|
| `LOUPE_API_URL` | `https://loupe-server.onrender.com` |
| `LOUPE_API_KEY` | the `lp_...` key from Step 3 |
| `NEXT_PUBLIC_SENTRY_DSN` | your Sentry DSN (same as server's) |

5. Deploy

**Verify:** Open the Vercel URL → you should see the traces list (empty for now).

> *Interview Q:* `LOUPE_API_KEY` in the dashboard — is this a security concern? *(It's a server env var, not exposed to the browser. In Next.js App Router, Server Components + Server Actions run on Vercel's infra. The key never goes to the browser. If we had browser-side fetch to the server, we'd need the `NEXT_PUBLIC_` prefix and the key would be in the page source — that would be a problem.)*

> *Interview Q:* `NEXT_PUBLIC_SENTRY_DSN` is public — is that fine? *(Yes — Sentry DSNs are designed to be public. They're write-only from the browser: you can POST errors to Sentry but you can't read data with them. Rate limits + project-level filtering prevent abuse.)*

## Render free tier gotchas

- **Cold starts:** Free tier spins down after 15 min of inactivity. First request after sleep takes ~30s (Render boots the container). For the demo, hit `/health` first to warm it up.
- **512 MB RAM:** FastAPI + asyncpg + Sentry is well under 200MB, no issue.
- **No persistent disk:** Any file written by the server is ephemeral. We don't write files (structured logs + Postgres), so this doesn't matter.

> *Interview Q:* How would you eliminate cold starts in production? *(Pay for the Starter plan $7/mo — always-on. Or use a cron job to ping /health every 5 min. Or migrate to Railway/Fly which have more generous free tiers without sleep.)*

## After deployment — seed demo data

```bash
cd examples/cinerater
# update .env: LOUPE_API_KEY=lp_... (live key), LOUPE_HOST=https://loupe-server.onrender.com
python -m examples.cinerater.agent "recommend a thriller from 2023"
python -m examples.cinerater.agent "best sci-fi movie from 2024"
python -m examples.cinerater.agent "top rated drama from 2022"
```

Open the Vercel dashboard — traces appear. Now record a screencast for the README.
