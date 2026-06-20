from pathlib import Path

from fastapi.testclient import TestClient

from engine.api import create_app
from engine.models import (
    AnalysisModel,
    CodeRef,
    Endpoint,
    Flow,
    FlowEdge,
    FlowNode,
    Project,
    RepoRef,
)


def _ref():
    return CodeRef(repo="edfx-api", file="r.py", line=1, snippet="x")


def _model():
    ep = Endpoint(id="edfx-api:GET:/edfx/v2/x", repo="edfx-api", method="GET",
                  path="/edfx/v2/x", handler_ref=_ref(), language="python")
    ui = FlowNode(id="ui:edfx-app-ui:edfxApiV2Url", repo="edfx-app-ui", label="edfxApiV2Url",
                  kind="ui", code_ref=_ref())
    route = FlowNode(id="route:edfx-api:GET:/edfx/v2/x", repo="edfx-api", label="GET /edfx/v2/x",
                     kind="route", code_ref=_ref())
    edge = FlowEdge(from_node=ui.id, to_node=route.id, kind="http", confidence=0.5)
    flow = Flow(endpoint_id=ep.id, nodes=[ui, route], edges=[edge])
    project = Project(id="edfx-flow", name="EDFX Flow",
                      repos=[RepoRef(url="u", folder="edfx-api", branch="master", sha="s")])
    return AnalysisModel(project=project, endpoints=[ep], flows=[flow])


def _client(tmp_path):
    store = {"edfx-flow": _model()}
    app = create_app(projects_dir=tmp_path, workspace=tmp_path / "ws", store=store)
    return TestClient(app)


def test_get_endpoints(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/projects/edfx-flow/endpoints")
    assert resp.status_code == 200
    assert resp.json()[0]["path"] == "/edfx/v2/x"
    assert resp.json()[0]["handlerRef"]["file"] == "r.py"  # camelCase contract


def test_get_flow_by_query(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/projects/edfx-flow/flow", params={"endpoint_id": "edfx-api:GET:/edfx/v2/x"})
    assert resp.status_code == 200
    assert resp.json()["endpointId"] == "edfx-api:GET:/edfx/v2/x"


def test_get_flow_node_by_query(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/projects/edfx-flow/flow-node",
                      params={"node_id": "route:edfx-api:GET:/edfx/v2/x"})
    assert resp.status_code == 200
    assert resp.json()["codeRef"]["file"] == "r.py"


def test_missing_flow_returns_404(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/projects/edfx-flow/flow", params={"endpoint_id": "nope"})
    assert resp.status_code == 404


import json


def test_list_projects(tmp_path):
    (tmp_path / "edfx-flow.json").write_text(
        json.dumps({"project": "edfx-flow", "repos": [{"url": "u", "folder": "edfx-api", "branch": "master"}]}),
        encoding="utf-8",
    )
    app = create_app(projects_dir=tmp_path, workspace=tmp_path / "ws", store={})
    client = TestClient(app)
    resp = client.get("/projects")
    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "edfx-flow"


def test_run_invokes_analyze_and_stores(tmp_path, monkeypatch):
    (tmp_path / "edfx-flow.json").write_text(
        json.dumps({"project": "edfx-flow", "repos": [{"url": "u", "folder": "edfx-api", "branch": "master"}]}),
        encoding="utf-8",
    )
    store: dict = {}
    monkeypatch.setattr("engine.api.analyze", lambda project, workspace: _model())
    app = create_app(projects_dir=tmp_path, workspace=tmp_path / "ws", store=store)
    client = TestClient(app)
    resp = client.post("/projects/edfx-flow/run")
    assert resp.status_code == 200
    assert resp.json() == {"endpoints": 1, "flows": 1}
    assert "edfx-flow" in store
    # now readable
    assert client.get("/projects/edfx-flow/endpoints").status_code == 200
