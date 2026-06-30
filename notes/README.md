# Loupe — Build Notes

Each file here covers one item from the CLAUDE.md build checklist. For every meaningful sub-step within an item: what was done, key learnings, and likely interview questions tied to the decisions made.

## Index

- [Item 1 — Repo initialized, monorepo structure set up](01-monorepo-scaffolding.md)
- [Item 2 — docker-compose.yml with Postgres running](02-docker-postgres.md)
- [Item 3 — FastAPI app with /health endpoint](03-fastapi-health.md)
- [Item 4 — Alembic migrations + 4-table schema](04-alembic-schema.md)
- [Item 5 — POST /v1/traces ingestion endpoint](05-traces-ingestion.md)
- [Item 6 — GET /v1/traces list endpoint](06-traces-list.md)
- [Item 7 — GET /v1/traces/{id} detail endpoint](07-traces-detail.md)
- [Item 8 — API key auth on all endpoints](08-auth-coverage.md)
- [Item 9 — SDK: @loupe.trace decorator](09-sdk-trace-decorator.md)
- [Item 10 — SDK: loupe.span() context manager](10-sdk-span.md)
- [Items 11–12 — SDK: OpenAI and Anthropic auto-instrumentation](11-12-sdk-integrations.md)
- [Item 13 — SDK: Groq auto-instrumentation](13-groq-instrumentation.md)
- [Item 14 — SDK: Batched async flush with retry](14-async-batch-flush.md)
- [Item 15 — Dashboard: Traces list page](15-dashboard-traces-list.md)
- [Item 16 — Dashboard: Trace detail + span tree](16-trace-detail-span-tree.md)
- [Item 17 — Dashboard: Replay UI](17-replay-ui.md)
- [Item 18 — Dashboard: Side-by-side replay diff](18-replay-diff.md)
- [Item 19 — Sentry + structlog](19-sentry-structlog.md)
- [Item 20 — CineRater example + SDK atexit fix](20-cinerater-example.md)
- [Item 21 — Deployment: Neon + Render + Vercel](21-deployment.md)
- [Item 22 — v2 Replay Engine: Design (time-travel debugger)](22-v2-replay-engine-design.md)
- [Item 23 — Server test suite (+ the async testing rabbit hole)](23-server-test-suite.md)
- [Item 24 — Branch replay engine (the heart of v2)](24-branch-replay-engine.md)
- [Item 25 — SDK-side replay (making the edit actually propagate)](25-sdk-side-replay.md)
- [Item 26 — Branch diff view (original vs counterfactual, side by side)](26-branch-diff-view.md)
