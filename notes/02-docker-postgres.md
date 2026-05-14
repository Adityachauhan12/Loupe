# Item 2 — docker-compose.yml with Postgres running

---

## Sub-step A — Writing the compose file

**What changed**

- Created `docker-compose.yml` at project root with one service: `db` (postgres:16-alpine).
- Added a healthcheck (`pg_isready` every 5s), a named volume (`loupe_db_data`) for persistence, env-var-driven credentials with defaults (`loupe`/`loupe`/`loupe`), and a port mapping.
- Added `.env.example` at the project root so users know which env vars compose reads.

**Learnings**

- **`postgres:16-alpine` vs `postgres:16`.** Alpine variant is ~80MB smaller (Alpine base + musl libc instead of Debian + glibc). Faster pulls, smaller surface area. Tradeoff: rare musl-vs-glibc bugs and slightly different DNS resolver behavior — almost never matters for Postgres specifically.
- **Healthchecks matter when other services depend on the DB.** A `depends_on` with `condition: service_healthy` won't start the server until the healthcheck passes. Without it, services race-start and the server crashes connecting to a not-yet-ready DB. We'll wire this in item 3+ when the server joins compose.
- **Named volumes vs bind mounts.** `loupe_db_data:/var/lib/postgresql/data` is a named volume — Docker manages the location. A bind mount (`./data:/var/lib/postgresql/data`) puts it in the repo. Named volumes are more portable across machines; bind mounts are easier to inspect/back-up directly. Named volume is the right default for a DB.
- **`pg_isready` does a lightweight TCP probe + auth check.** It does NOT run a real query — it confirms the socket is open and the user can authenticate. Good enough for "is Postgres up" but doesn't catch DB-level issues like "is the schema valid".
- **Env-var defaults in compose: `${POSTGRES_USER:-loupe}`.** Bash-style substitution. Compose reads from a `.env` file in the same dir as `docker-compose.yml` by default. If neither the shell nor `.env` provides it, the `:-loupe` fallback kicks in.

**Interview questions**

1. What's the difference between a named volume and a bind mount in Docker? *(named = Docker-managed location, portable; bind = host path, inspectable)*
2. Why a healthcheck on the DB service? *(downstream services use `depends_on: condition: service_healthy` to wait for true readiness, not just container start)*
3. `postgres:16-alpine` vs `postgres:16` — what's the tradeoff? *(size and surface area vs glibc compatibility; almost always Alpine for stateless DBs)*

---

## Sub-step B — Port conflict resolution (5432 → 5433)

**What changed**

- Discovered two things on host port 5432: a native Postgres (Homebrew) listening on 127.0.0.1, and another project's container `backend-db-1` bound to 0.0.0.0:5432.
- Changed the compose port mapping from `5432:5432` to `5433:5432`. Container still listens on 5432 internally; only the host-side port changed.
- Updated `DATABASE_URL` example in CLAUDE.md to reflect `localhost:5433`.

**Learnings**

- **`HOST:CONTAINER` port mapping.** Left side = host port (what tools on your machine connect to). Right side = container port (what the process inside binds to). Changing the host side is non-disruptive — the container itself doesn't know or care.
- **Inside Docker networks, services reach each other by service name on the container port.** When the server service joins compose later, it'll connect to `db:5432`, NOT `localhost:5433`. The host port mapping is irrelevant for in-network traffic.
- **`lsof -nP -iTCP:<port> -sTCP:LISTEN`** is the canonical "what's listening on this port" command on macOS/Linux. The `-n` skips DNS resolution, `-P` keeps ports numeric (don't translate 5432 to "postgresql"). Worth memorizing.

**Interview questions**

1. A teammate gets "port 5432 already allocated" when running `docker compose up`. Walk through your debugging steps. *(lsof to find the listener; decide: kill the other process, change the mapping, or use a Docker network)*
2. In a docker-compose network, your app service connects to `db:5432` and works locally. The same code in production connects to a managed Postgres. What changes, and what stays the same? *(`DATABASE_URL` changes; everything else stays. That's why DB URL belongs in env, not code.)*

---

## Sub-step C — Verifying it actually works

**What changed**

- `docker compose up -d` started the container.
- Polled `docker inspect` for `Health.Status == "healthy"`, then ran `psql -c "SELECT version();"` inside the container to confirm.
- Verified host-port 5433 reachability with `pg_isready -h host.docker.internal -p 5433`.

**Learnings**

- **Image start success ≠ service ready.** The container can be `running` while Postgres is still doing initdb on first boot. Always poll the healthcheck or run an actual query before depending on the service.
- **`host.docker.internal`** is a Docker-Desktop-specific DNS name that resolves to the host machine from inside containers. Useful for testing host-mapped ports from inside another container. Doesn't exist on plain Linux Docker (use `--add-host=host.docker.internal:host-gateway` or `172.17.0.1`).
- **First image pull will be slow.** ~100MB layer for postgres-alpine. Subsequent runs are instant because layers are cached.

**Interview questions**

1. "The container's running but my app can't connect." How do you debug? *(check healthcheck status; check port mapping; check if Postgres finished initdb; check network mode)*
2. What does `docker compose up -d` actually do step-by-step? *(parse compose file → pull images if missing → create network → create volume → create container → start container; `-d` = detach from logs)*
