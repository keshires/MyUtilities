"""Read-only catalog dashboard for Day2Day utilities. Serves the SPA at /app/."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from dashboard.manifest import ManifestError, load_manifest
from dashboard.runs import list_runs, resolve_artifact

app = FastAPI(title="Day2Day Utilities Catalog")

_DASHBOARD_DIR = Path(__file__).resolve().parent
_APP_DIR = _DASHBOARD_DIR / "app"


@app.get("/")
def _root() -> RedirectResponse:
    return RedirectResponse(url="/app/")


@app.get("/api/utilities")
def get_utilities() -> JSONResponse:
    try:
        m = load_manifest()
    except ManifestError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return JSONResponse(m.model_dump())


@app.get("/api/utilities/{uid}/runs")
def get_runs(uid: str) -> JSONResponse:
    try:
        m = load_manifest()
    except ManifestError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    match = [u for u in m.utilities if u.id == uid]
    if not match:
        raise HTTPException(status_code=404, detail=f"Unknown utility: {uid}")
    return JSONResponse({"runs": list_runs(match[0])})


@app.get("/download/{kind}/{name:path}")
def download(kind: str, name: str) -> FileResponse:
    target = resolve_artifact(kind, name)
    if target is None:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(target)


app.mount("/app", StaticFiles(directory=_APP_DIR, html=True), name="dashboard")