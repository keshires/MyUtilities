"""FastAPI read API over analyzed models (one in-memory store per app)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException

from engine.analyze import analyze
from engine.ingest import load_project
from engine.models import AnalysisModel


def create_app(projects_dir, workspace, store: dict[str, AnalysisModel] | None = None) -> FastAPI:
    app = FastAPI(title="DocuProj")
    projects_dir = Path(projects_dir)
    store = store if store is not None else {}

    def _model(pid: str) -> AnalysisModel:
        if pid not in store:
            raise HTTPException(status_code=404, detail=f"project '{pid}' not analyzed")
        return store[pid]

    @app.get("/projects")
    def list_projects():
        return [load_project(path).model_dump(by_alias=True) for path in sorted(projects_dir.glob("*.json"))]

    @app.post("/projects/{pid}/run")
    def run(pid: str):
        project = load_project(projects_dir / f"{pid}.json")
        model = analyze(project, workspace)
        store[pid] = model
        return {"endpoints": len(model.endpoints), "flows": len(model.flows)}

    @app.get("/projects/{pid}/endpoints")
    def endpoints(pid: str):
        return [e.model_dump(by_alias=True) for e in _model(pid).endpoints]

    @app.get("/projects/{pid}/flow")
    def flow(pid: str, endpoint_id: str):
        for fl in _model(pid).flows:
            if fl.endpoint_id == endpoint_id:
                return fl.model_dump(by_alias=True)
        raise HTTPException(status_code=404, detail="flow not found")

    @app.get("/projects/{pid}/flow-node")
    def flow_node(pid: str, node_id: str):
        for fl in _model(pid).flows:
            for node in fl.nodes:
                if node.id == node_id:
                    return node.model_dump(by_alias=True)
        raise HTTPException(status_code=404, detail="flow node not found")

    return app
