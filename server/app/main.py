from fastapi import FastAPI

from app.routers import traces

app = FastAPI(title="Loupe", version="0.1.0")
app.include_router(traces.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
