# DocuProj API + Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tie the engine together with an `analyze()` orchestration (ingest → detect language → parse → link → cache) and expose the resulting `AnalysisModel` over a FastAPI read API the dashboard will consume.

**Architecture:** `detect_language()` infers a repo's language from marker files. `analyze(project, workspace, cache)` runs the full pipeline and caches the model. A FastAPI app (`create_app`) holds an in-memory store of analyzed models: `POST /projects/{id}/run` calls `analyze` and stores the result; `GET` endpoints serve projects, endpoints, a flow, and a flow node. Endpoint/node ids contain `/`, so flow lookups use query params (documented deviation from the spec's path-style URLs).

**Tech Stack:** Python 3.12, pydantic v2, FastAPI, httpx (TestClient), pytest. Orchestration tests run against local fixture source trees with an injected ingest (no network); API tests use `fastapi.testclient.TestClient`.

---

## Roadmap context

**Plan 5 of the Phase-1 MVP vertical.** Consumes Plan 2 (ingest), Plan 3 (parse), Plan 4 (link). Produces the HTTP surface Plan 6 (Dashboard) renders. The diagram/writeup/export endpoints (spec §5 req 9-11) remain deferred (need Mermaid/Claude/python-docx).

## File Structure

```
DocuProj/
  requirements.txt          # + fastapi, httpx
  engine/
    analyze.py              # detect_language(), analyze()
    api.py                  # create_app() FastAPI read API
  tests/
    fixtures/analyze/
      api/svc.py            # FastAPI router under /edfx/v2 (python fixture)
      ui/environment.ts     # endPointConfig with edfx/v2 base URL (angular fixture)
    test_analyze.py
    test_api.py
```

---

### Task 1: `detect_language()`

**Files:**
- Create: `DocuProj/engine/analyze.py`
- Test: `DocuProj/tests/test_analyze.py`

Infers language from marker files: `angular.json` → angular; `requirements.txt`/`pyproject.toml`/`main.py` → python; `package.json` → typescript; else None.

- [ ] **Step 1: Write the failing test** — `DocuProj/tests/test_analyze.py`

```python
from engine.analyze import detect_language


def test_detect_angular(tmp_path):
    (tmp_path / "angular.json").write_text("{}", encoding="utf-8")
    assert detect_language(tmp_path) == "angular"


def test_detect_python(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    assert detect_language(tmp_path) == "python"


def test_detect_typescript(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert detect_language(tmp_path) == "typescript"


def test_detect_unknown(tmp_path):
    assert detect_language(tmp_path) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_analyze.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.analyze'`.

- [ ] **Step 3: Implement** — `DocuProj/engine/analyze.py`

```python
"""Orchestration: ingest -> detect language -> parse -> link -> cache."""

from __future__ import annotations

from pathlib import Path

from engine.cache import cache_key
from engine.ingest import ingest
from engine.linker import link
from engine.models import AnalysisModel, Project, RepoRef
from engine.parsers import parse


def detect_language(repo_path) -> str | None:
    p = Path(repo_path)
    if (p / "angular.json").exists():
        return "angular"
    if (p / "requirements.txt").exists() or (p / "pyproject.toml").exists() or (p / "main.py").exists():
        return "python"
    if (p / "package.json").exists():
        return "typescript"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_analyze.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add DocuProj/engine/analyze.py DocuProj/tests/test_analyze.py
git commit -m "feat(analyze): add detect_language"
```

---

### Task 2: `analyze()` pipeline

**Files:**
- Modify: `DocuProj/engine/analyze.py`
- Create: `DocuProj/tests/fixtures/analyze/api/svc.py`
- Create: `DocuProj/tests/fixtures/analyze/ui/environment.ts`
- Modify: `DocuProj/tests/test_analyze.py` (append)

`analyze` ingests, parses each repo by detected (or supplied) language, links, and caches. Tested with an injected `ingest` pointing at local fixtures (no clone), with aligned paths so a real flow is produced.

- [ ] **Step 1: Create the fixtures**

`DocuProj/tests/fixtures/analyze/api/svc.py`:

```python
from fastapi import APIRouter

v2 = APIRouter(prefix="/edfx/v2")


@v2.get("/tools/customPd")
async def custom_pd():
    return {}
```

`DocuProj/tests/fixtures/analyze/ui/environment.ts`:

```typescript
export const environment = {
  endPointConfig: {
    edfxApiV2Url: 'https://api.example.net/edfx/v2',
  },
};
```

- [ ] **Step 2: Write the failing test** — append to `DocuProj/tests/test_analyze.py`

```python
from pathlib import Path

from engine.analyze import analyze
from engine.cache import Cache, cache_key
from engine.ingest import ResolvedRepo
from engine.models import Project, RepoRef

_FIX = Path(__file__).resolve().parent / "fixtures" / "analyze"


def _project():
    return Project(
        id="t",
        name="t",
        repos=[
            RepoRef(url="u-ui", folder="ui", branch="main"),
            RepoRef(url="u-api", folder="api", branch="master"),
        ],
    )


def _fake_ingest(monkeypatch):
    def fake(project, workspace, branch_overrides=None):
        return [
            ResolvedRepo(url="u-ui", folder="ui", branch="main", sha="uiSHA", path=str(_FIX / "ui")),
            ResolvedRepo(url="u-api", folder="api", branch="master", sha="apiSHA", path=str(_FIX / "api")),
        ]
    monkeypatch.setattr("engine.analyze.ingest", fake)


def test_analyze_builds_and_caches_model(tmp_path, monkeypatch):
    _fake_ingest(monkeypatch)
    cache = Cache(tmp_path / "cache")
    model = analyze(_project(), tmp_path / "ws", cache=cache, languages={"ui": "angular", "api": "python"})
    # one inbound endpoint from the api fixture
    assert any(e.path == "/edfx/v2/tools/customPd" for e in model.endpoints)
    # config /edfx/v2 prefixes the route -> one cross-repo flow
    assert len(model.flows) == 1
    # resolved shas flow into the cache key
    cached = cache.get(cache_key(model.project))
    assert cached == model
    assert model.project.repos[0].sha in ("uiSHA", "apiSHA")


def test_analyze_autodetects_language(tmp_path, monkeypatch):
    _fake_ingest(monkeypatch)
    # api fixture dir has no requirements.txt; add marker so detection picks python
    (_FIX / "api" / "main.py").write_text("", encoding="utf-8")
    try:
        model = analyze(_project(), tmp_path / "ws")  # no languages -> detect
        assert any(e.path == "/edfx/v2/tools/customPd" for e in model.endpoints)
    finally:
        (_FIX / "api" / "main.py").unlink()
```

- [ ] **Step 3: Implement** — append to `DocuProj/engine/analyze.py`

```python
def analyze(project, workspace, cache=None, languages=None, resolver=None) -> AnalysisModel:
    languages = languages or {}
    resolved = ingest(project, workspace)
    facts = []
    for repo in resolved:
        lang = languages.get(repo.folder) or detect_language(repo.path)
        if lang is None:
            continue
        facts.append(parse(repo.path, lang, repo=repo.folder))
    resolved_project = Project(
        id=project.id,
        name=project.name,
        repos=[
            RepoRef(url=r.url, folder=r.folder, branch=r.branch, sha=r.sha) for r in resolved
        ],
    )
    model = link(facts, resolved_project, resolver=resolver)
    if cache is not None:
        cache.put(cache_key(resolved_project), model)
    return model
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_analyze.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add DocuProj/engine/analyze.py DocuProj/tests/fixtures/analyze DocuProj/tests/test_analyze.py
git commit -m "feat(analyze): add analyze() ingest->parse->link->cache pipeline"
```

---

### Task 3: FastAPI read API (projects, endpoints, flow, flow-node)

**Files:**
- Modify: `DocuProj/requirements.txt`
- Create: `DocuProj/engine/api.py`
- Test: `DocuProj/tests/test_api.py`

`create_app(projects_dir, workspace, store)` exposes read endpoints over an in-memory `store` (project id → `AnalysisModel`). Flow/flow-node use query params (ids contain `/`).

- [ ] **Step 1: Add deps** — append to `DocuProj/requirements.txt`

```text
fastapi>=0.110
httpx>=0.27
```

- [ ] **Step 2: Install**

Run (from `DocuProj/`): `.\.venv\Scripts\pip install -r requirements.txt`
Expected: fastapi + httpx install.

- [ ] **Step 3: Write the failing test** — `DocuProj/tests/test_api.py`

```python
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
```

- [ ] **Step 4: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.api'`.

- [ ] **Step 5: Implement** — `DocuProj/engine/api.py`

```python
"""FastAPI read API over analyzed models (one in-memory store per app)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException

from engine.analyze import analyze
from engine.ingest import load_project
from engine.models import AnalysisModel, Project


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
        projects = []
        for path in sorted(projects_dir.glob("*.json")):
            projects.append(load_project(path).model_dump(by_alias=True))
        return projects

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
```

Remove the unused `_dump` helper before finishing (it is not referenced).

- [ ] **Step 6: Run test to verify it passes**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_api.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add DocuProj/requirements.txt DocuProj/engine/api.py DocuProj/tests/test_api.py
git commit -m "feat(api): add FastAPI read endpoints (projects, endpoints, flow, flow-node)"
```

---

### Task 4: `POST /run` + `/projects` listing tests + exports

**Files:**
- Modify: `DocuProj/engine/__init__.py`
- Test: `DocuProj/tests/test_api.py` (append)

Covers the run endpoint (with `analyze` monkeypatched to avoid clones) and the projects listing, and exports `create_app` / `analyze` / `detect_language`.

- [ ] **Step 1: Write the failing test** — append to `DocuProj/tests/test_api.py`

```python
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
```

- [ ] **Step 2: Run the new tests**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_api.py -v`
Expected: PASS — these exercise the `/projects` listing and `POST /run` endpoints already implemented in Task 3 (run is monkeypatched to skip cloning). This task's substantive addition is the public exports in Step 3.

- [ ] **Step 3: Implement exports** — add to `DocuProj/engine/__init__.py`

Add this import after the `from engine.linker import ...` line:

```python
from engine.analyze import analyze, detect_language
from engine.api import create_app
```

And extend `__all__` with (alphabetical insertion):

```python
    "analyze",
    "create_app",
    "detect_language",
```

- [ ] **Step 4: Run the full test suite**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest -v`
Expected: PASS — Plan 1-4 (38) + Plan 5 (12) = 50 tests.

- [ ] **Step 5: Commit**

```bash
git add DocuProj/engine/__init__.py DocuProj/tests/test_api.py
git commit -m "feat(api): add run endpoint coverage, projects listing, and exports"
```

---

## Self-Review

**Spec coverage (API §5 + orchestration §3):**
- `analyze` = ingest → parse → link → cache (the `POST /run` "ingest+analyze, always latest") — Task 2 ✓
- Language detection so `project.json` stays `{url,folder,branch}` — Task 1 ✓
- `GET /projects` — Task 3/4 ✓
- `POST /projects/{id}/run` — Task 3 (impl) + Task 4 (test) ✓
- `GET /projects/{id}/endpoints` (req 6) — Task 3 ✓
- `GET .../flow` (req 7) and `.../flow-node` (req 8 popup) — Task 3 ✓ (query-param ids; documented deviation since ids contain `/`)
- camelCase JSON contract preserved (`by_alias=True`) — Task 3 ✓
- Deferred (correctly): diagram/writeup/export (req 9-11, need Mermaid/Claude/python-docx); job/async semantics (run is synchronous for MVP); persistent store (in-memory per app for MVP).

**Placeholder scan:** The `_dump` stub in Task 3 is explicitly flagged for removal in the same step (not shipped). No other TBD/TODO; every code step is complete; run steps show commands + expected results.

**Type consistency:** `detect_language(repo_path)`, `analyze(project, workspace, cache, languages, resolver)`, and `create_app(projects_dir, workspace, store)` are referenced identically across tasks/tests. The API serializes with `by_alias=True` to match the Plan 1 camelCase contract. Store keys are project ids throughout.
