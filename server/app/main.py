import logging

import sentry_sdk
import structlog
from fastapi import FastAPI
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.config import settings
from app.routers import replays, traces

# ── Sentry ─────────────────────────────────────────────────────────────────
# Only activates when SENTRY_DSN is set — dev works without it.
if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        traces_sample_rate=0.1,   # trace 10% of requests for performance monitoring
        environment=settings.environment,
        send_default_pii=False,
    )

# ── structlog ──────────────────────────────────────────────────────────────
# Dev: human-readable coloured output.
# Production: JSON one-line-per-event (grep-friendly, parseable by log aggregators).
_dev = settings.environment == "development"

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if _dev else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

# Route standard library logging through structlog so uvicorn logs
# get the same format as our app logs.
logging.basicConfig(
    format="%(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()],
)

# ── App ────────────────────────────────────────────────────────────────────
app = FastAPI(title="Loupe", version="0.1.0")
app.include_router(traces.router)
app.include_router(replays.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
