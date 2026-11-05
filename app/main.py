"""FastAPI app: JSON API plus the static Leaflet UI."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.api.routes import router

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Global Conflict Map")


@app.get("/health")
def health() -> dict[str, str]:
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
