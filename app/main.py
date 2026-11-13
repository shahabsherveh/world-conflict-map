"""FastAPI app: JSON API plus the static Leaflet UI."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.api.routes import router

STATIC_DIR = Path(__file__).parent / "static"

DESCRIPTION = """\
Interactive map of armed conflicts worldwide, browsable across time.

The JSON API serves conflicts and their events filtered by time range, exposes
manual edit/create endpoints (audited in `edit_log`), and reports pipeline
freshness. The Leaflet UI is served from `/`; interactive documentation is
available at `/docs` (Swagger UI) and `/redoc`.

Data source: GDELT 2.0 raw event files, refreshed daily.
"""

TAGS_METADATA = [
    {"name": "conflicts", "description": "Query, create, and edit conflicts."},
    {"name": "events", "description": "Query, create, and edit events."},
    {"name": "pipeline", "description": "Ingestion run history and freshness."},
    {"name": "sources", "description": "Data-source transparency."},
    {"name": "system", "description": "Liveness probe."},
]

app = FastAPI(
    title="Global Conflict Map",
    summary="Map armed conflicts worldwide, browsable across time.",
    description=DESCRIPTION,
    version="0.1.0",
    openapi_tags=TAGS_METADATA,
)


@app.get("/health", tags=["system"], summary="Liveness probe")
def health() -> dict[str, str]:
    """Return 200 with the service status.

    Kept trivial on purpose: CI and deploy curl this endpoint as the container
    liveness probe, so it must stay cheap and 200 even when the DB is missing
    or empty.
    """
    return {"status": "ok"}


@app.middleware("http")
async def no_store_static(request: Request, call_next):
    """Always revalidate HTML so UI edits show up without a hard refresh."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.include_router(router)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
