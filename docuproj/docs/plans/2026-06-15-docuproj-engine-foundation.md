# DocuProj Engine Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the DocuProj engine foundation — the stable §4 data model and the SHA+analyzer-version cache — so every later subsystem (ingestor, parsers, linker, API, dashboard) reads one validated contract.

**Architecture:** A Python package `DocuProj/engine/` defines the analysis data model as pydantic v2 models that serialize to the camelCase JSON contract the dashboard consumes. A content-addressed cache stores a fully-linked `AnalysisModel` keyed by `(repo SHAs + analyzer version)`, so an unchanged project re-serves cached results with zero re-parsing.

**Tech Stack:** Python 3.11+, pydantic v2 (validation + JSON), pytest. Per repo convention each project folder owns its `requirements.txt` and `.venv` (mirrors `Day2Day_Utillites`).

---

## Roadmap context (where this fits)

This is **Plan 1 of the Phase-1 MVP vertical**. Subsequent plans (separate files): 2-Ingestor, 3-Parsers, 4-Linker, 5-API, 6-Dashboard. This plan has **no external-repo dependency** and is fully unit-testable.

## File Structure

```
DocuProj/
  requirements.txt        # pydantic, pytest
  pytest.ini              # pytest config (testpaths, rootdir)
  .gitignore              # .venv/, .workspace/, __pycache__/, *.pyc
  engine/
    __init__.py           # package marker, exports public model + cache
    version.py            # ANALYZER_VERSION constant
    models.py             # CodeRef, Endpoint, FlowNode, FlowEdge, Flow, RepoRef, Project, AnalysisModel
    cache.py              # cache_key(), Cache (get/put)
  tests/
    __init__.py
    test_smoke.py         # confirms toolchain runs
    test_models.py        # model validation + JSON round-trip
    test_cache.py         # key stability + put/get round-trip
```

Each file has one responsibility: `models.py` is the data contract, `cache.py` is persistence, `version.py` is the single source of the analyzer version (changing it invalidates all caches by design).

---

### Task 1: Scaffold the engine package and toolchain

**Files:**
- Create: `DocuProj/requirements.txt`
- Create: `DocuProj/pytest.ini`
- Create: `DocuProj/.gitignore`
- Create: `DocuProj/engine/__init__.py`
- Create: `DocuProj/tests/__init__.py`
- Test: `DocuProj/tests/test_smoke.py`

- [ ] **Step 1: Create `DocuProj/requirements.txt`**

```text
pydantic>=2.6,<3
pytest>=8.0
```

- [ ] **Step 2: Create `DocuProj/pytest.ini`**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_functions = test_*
```

- [ ] **Step 3: Create `DocuProj/.gitignore`**

```text
.venv/
.workspace/
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 4: Create empty package markers**

`DocuProj/engine/__init__.py`:

```python
"""DocuProj analysis engine."""
```

`DocuProj/tests/__init__.py`:

```python
```

- [ ] **Step 5: Write the smoke test** — `DocuProj/tests/test_smoke.py`

```python
def test_pydantic_importable():
    import pydantic

    assert pydantic.VERSION.startswith("2")
```

- [ ] **Step 6: Create venv and install deps**

Run (PowerShell, from `DocuProj/`):

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements.txt
```

Expected: pydantic 2.x and pytest install without error.

- [ ] **Step 7: Run the smoke test**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_smoke.py -v`
Expected: PASS (1 passed).

- [ ] **Step 8: Commit**

```bash
git add DocuProj/requirements.txt DocuProj/pytest.ini DocuProj/.gitignore DocuProj/engine/__init__.py DocuProj/tests/__init__.py DocuProj/tests/test_smoke.py
git commit -m "feat(engine): scaffold DocuProj engine package and toolchain"
```

---

### Task 2: `CodeRef` and `Endpoint` models

**Files:**
- Create: `DocuProj/engine/models.py`
- Test: `DocuProj/tests/test_models.py`

`CodeRef` powers the step popup (§4, req 8). `Endpoint` is the §4 endpoint shape; its JSON uses `handlerRef` (camelCase), so the model uses a field alias.

- [ ] **Step 1: Write the failing test** — `DocuProj/tests/test_models.py`

```python
from engine.models import CodeRef, Endpoint


def test_coderef_round_trips():
    ref = CodeRef(repo="edfx-api", file="src/routes/entity.ts", line=42, snippet="router.get(...)")
    assert ref.line == 42
    assert CodeRef.model_validate(ref.model_dump()) == ref


def test_endpoint_serializes_camelcase_handler_ref():
    ref = CodeRef(repo="edfx-api", file="a.ts", line=1, snippet="x")
    ep = Endpoint(
        id="ep1",
        repo="edfx-api",
        method="GET",
        path="/v2/entities/{id}",
        handler_ref=ref,
        language="typescript",
    )
    dumped = ep.model_dump(by_alias=True)
    assert dumped["handlerRef"]["file"] == "a.ts"
    # Round-trips back from camelCase JSON
    assert Endpoint.model_validate(dumped) == ep
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.models'`.

- [ ] **Step 3: Write minimal implementation** — `DocuProj/engine/models.py`

```python
"""DocuProj analysis data model (§4 of the design spec).

All models serialize to the camelCase JSON contract the dashboard consumes.
Python attributes stay snake_case; camelCase is applied via field aliases.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    # Accept either snake_case (Python) or the camelCase alias (JSON) on input.
    model_config = ConfigDict(populate_by_name=True)


class CodeRef(_Model):
    repo: str
    file: str
    line: int
    snippet: str


class Endpoint(_Model):
    id: str
    repo: str
    method: str
    path: str
    handler_ref: CodeRef = Field(alias="handlerRef")
    language: str
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_models.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add DocuProj/engine/models.py DocuProj/tests/test_models.py
git commit -m "feat(engine): add CodeRef and Endpoint models"
```

---

### Task 3: Flow models (`FlowNode`, `FlowEdge`, `Flow`)

**Files:**
- Modify: `DocuProj/engine/models.py`
- Test: `DocuProj/tests/test_models.py` (append)

`FlowEdge.from`/`to` are reserved/awkward in Python, so attributes are `from_node`/`to_node` with `from`/`to` aliases. `kind` and `confidence` are validated (§4: kind enums, confidence 0.0-1.0).

- [ ] **Step 1: Write the failing test** — append to `DocuProj/tests/test_models.py`

```python
import pytest
from pydantic import ValidationError

from engine.models import Flow, FlowEdge, FlowNode


def test_flowedge_uses_from_to_aliases():
    edge = FlowEdge(from_node="a", to_node="b", kind="http", confidence=0.9)
    dumped = edge.model_dump(by_alias=True)
    assert dumped["from"] == "a" and dumped["to"] == "b"
    assert FlowEdge.model_validate({"from": "a", "to": "b", "kind": "http", "confidence": 0.9}) == edge


def test_flowedge_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        FlowEdge(from_node="a", to_node="b", kind="http", confidence=1.5)


def test_flowedge_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        FlowEdge(from_node="a", to_node="b", kind="teleport", confidence=0.5)


def test_flow_round_trips():
    ref = CodeRef(repo="edfx-app-ui", file="App.tsx", line=10, snippet="api.get('/x')")
    node = FlowNode(id="n1", repo="edfx-app-ui", label="get entity", kind="ui", code_ref=ref)
    edge = FlowEdge(from_node="n1", to_node="n2", kind="http", confidence=1.0)
    flow = Flow(endpoint_id="ep1", nodes=[node], edges=[edge])
    dumped = flow.model_dump(by_alias=True)
    assert dumped["endpointId"] == "ep1"
    assert dumped["nodes"][0]["codeRef"]["file"] == "App.tsx"
    assert Flow.model_validate(dumped) == flow
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'Flow'`.

- [ ] **Step 3: Write minimal implementation** — append to `DocuProj/engine/models.py`

Add `Literal` to the import line so it reads:

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
```

Append the models:

```python
class FlowNode(_Model):
    id: str
    repo: str
    label: str
    kind: Literal["ui", "route", "fn", "outbound"]
    code_ref: CodeRef = Field(alias="codeRef")


class FlowEdge(_Model):
    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    kind: Literal["calls", "http"]
    confidence: float = Field(ge=0.0, le=1.0)


class Flow(_Model):
    endpoint_id: str = Field(alias="endpointId")
    nodes: list[FlowNode]
    edges: list[FlowEdge]
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_models.py -v`
Expected: PASS (all model tests pass).

- [ ] **Step 5: Commit**

```bash
git add DocuProj/engine/models.py DocuProj/tests/test_models.py
git commit -m "feat(engine): add Flow node/edge/flow models with validation"
```

---

### Task 4: `RepoRef`, `Project`, and `AnalysisModel`

**Files:**
- Modify: `DocuProj/engine/models.py`
- Modify: `DocuProj/engine/__init__.py`
- Test: `DocuProj/tests/test_models.py` (append)

`RepoRef.sha` is `None` until the ingestor resolves HEAD. `AnalysisModel` is the cached, API-served aggregate (project + endpoints + flows).

- [ ] **Step 1: Write the failing test** — append to `DocuProj/tests/test_models.py`

```python
from engine.models import AnalysisModel, Project, RepoRef


def test_reporef_sha_optional_until_ingest():
    repo = RepoRef(url="https://x/edfx-api", folder="edfx-api", branch="main")
    assert repo.sha is None


def test_analysis_model_round_trips():
    ref = CodeRef(repo="edfx-api", file="a.ts", line=1, snippet="x")
    ep = Endpoint(id="ep1", repo="edfx-api", method="GET", path="/x", handler_ref=ref, language="typescript")
    flow = Flow(endpoint_id="ep1", nodes=[], edges=[])
    project = Project(
        id="edfx-flow",
        name="EDFX Flow",
        repos=[RepoRef(url="https://x/edfx-api", folder="edfx-api", branch="main", sha="abc123")],
    )
    model = AnalysisModel(project=project, endpoints=[ep], flows=[flow])
    assert AnalysisModel.model_validate_json(model.model_dump_json(by_alias=True)) == model


def test_public_exports():
    import engine

    assert hasattr(engine, "AnalysisModel")
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'AnalysisModel'`.

- [ ] **Step 3: Write minimal implementation** — append to `DocuProj/engine/models.py`

```python
class RepoRef(_Model):
    url: str
    folder: str
    branch: str
    sha: str | None = None


class Project(_Model):
    id: str
    name: str
    repos: list[RepoRef]


class AnalysisModel(_Model):
    project: Project
    endpoints: list[Endpoint]
    flows: list[Flow]
```

Then set `DocuProj/engine/__init__.py` to:

```python
"""DocuProj analysis engine."""

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

__all__ = [
    "AnalysisModel",
    "CodeRef",
    "Endpoint",
    "Flow",
    "FlowEdge",
    "FlowNode",
    "Project",
    "RepoRef",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add DocuProj/engine/models.py DocuProj/engine/__init__.py DocuProj/tests/test_models.py
git commit -m "feat(engine): add RepoRef, Project, AnalysisModel and public exports"
```

---

### Task 5: Analyzer version and `cache_key`

**Files:**
- Create: `DocuProj/engine/version.py`
- Create: `DocuProj/engine/cache.py`
- Test: `DocuProj/tests/test_cache.py`

The cache key is content-addressed by `(analyzer version + every repo's folder:sha)` (§4 cache strategy). Same inputs → same key; any SHA change or a version bump → new key.

- [ ] **Step 1: Write the failing test** — `DocuProj/tests/test_cache.py`

```python
from engine.cache import cache_key
from engine.models import Project, RepoRef


def _project(sha_a="aaa", sha_b="bbb"):
    return Project(
        id="edfx-flow",
        name="EDFX Flow",
        repos=[
            RepoRef(url="https://x/edfx-api", folder="edfx-api", branch="main", sha=sha_a),
            RepoRef(url="https://x/edfx-ui", folder="edfx-app-ui", branch="main", sha=sha_b),
        ],
    )


def test_cache_key_is_stable():
    assert cache_key(_project()) == cache_key(_project())


def test_cache_key_independent_of_repo_order():
    p1 = _project()
    p2 = Project(id="edfx-flow", name="EDFX Flow", repos=list(reversed(p1.repos)))
    assert cache_key(p1) == cache_key(p2)


def test_cache_key_changes_with_sha():
    assert cache_key(_project()) != cache_key(_project(sha_a="zzz"))
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.cache'`.

- [ ] **Step 3: Write minimal implementation**

`DocuProj/engine/version.py`:

```python
"""Single source of the analyzer version. Bumping this invalidates all caches."""

ANALYZER_VERSION = "0.1.0"
```

`DocuProj/engine/cache.py`:

```python
"""Content-addressed cache for AnalysisModel, keyed by (analyzer version + repo SHAs)."""

from __future__ import annotations

import hashlib

from engine.models import Project
from engine.version import ANALYZER_VERSION


def cache_key(project: Project) -> str:
    parts = sorted(f"{r.folder}:{r.sha}" for r in project.repos)
    raw = "|".join([ANALYZER_VERSION, *parts])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_cache.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add DocuProj/engine/version.py DocuProj/engine/cache.py DocuProj/tests/test_cache.py
git commit -m "feat(engine): add analyzer version and content-addressed cache_key"
```

---

### Task 6: `Cache` get/put (filesystem JSON store)

**Files:**
- Modify: `DocuProj/engine/cache.py`
- Test: `DocuProj/tests/test_cache.py` (append)

A miss returns `None`; `put` then `get` returns an equal model. Stored as camelCase JSON under the cache root.

- [ ] **Step 1: Write the failing test** — append to `DocuProj/tests/test_cache.py`

```python
from engine.cache import Cache
from engine.models import AnalysisModel


def _model():
    return AnalysisModel(project=_project(), endpoints=[], flows=[])


def test_cache_miss_returns_none(tmp_path):
    cache = Cache(tmp_path)
    assert cache.get("does-not-exist") is None


def test_cache_put_then_get_round_trips(tmp_path):
    cache = Cache(tmp_path)
    model = _model()
    key = cache_key(model.project)
    cache.put(key, model)
    assert cache.get(key) == model


def test_cache_writes_camelcase_json(tmp_path):
    cache = Cache(tmp_path)
    model = _model()
    key = cache_key(model.project)
    cache.put(key, model)
    text = (tmp_path / f"{key}.json").read_text(encoding="utf-8")
    assert '"project"' in text
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_cache.py -v`
Expected: FAIL with `ImportError: cannot import name 'Cache'`.

- [ ] **Step 3: Write minimal implementation** — append to `DocuProj/engine/cache.py`

Add to the imports at the top of the file:

```python
from pathlib import Path

from engine.models import AnalysisModel, Project
```

(The existing `from engine.models import Project` line is now redundant — merge it into the line above.)

Append the class:

```python
class Cache:
    """Filesystem JSON cache. One file per key: <root>/<key>.json."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> AnalysisModel | None:
        path = self.root / f"{key}.json"
        if not path.exists():
            return None
        return AnalysisModel.model_validate_json(path.read_text(encoding="utf-8"))

    def put(self, key: str, model: AnalysisModel) -> None:
        path = self.root / f"{key}.json"
        path.write_text(model.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run the full test suite**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest -v`
Expected: PASS (all tests across smoke, models, cache).

- [ ] **Step 5: Commit**

```bash
git add DocuProj/engine/cache.py DocuProj/tests/test_cache.py
git commit -m "feat(engine): add filesystem Cache get/put for AnalysisModel"
```

---

## Self-Review

**Spec coverage (§4 data model + cache):**
- CodeRef, Endpoint, FlowNode, FlowEdge, Flow, RepoRef, Project — Tasks 2-4 ✓
- AnalysisModel aggregate (API-served, cached) — Task 4 ✓
- `confidence: 0.0-1.0` and `kind` enum validation — Task 3 ✓
- camelCase JSON contract (handlerRef, codeRef, endpointId, from/to) — Tasks 2-4 ✓
- Cache keyed by `(SHA + analyzer version)`; reuse on unchanged inputs — Tasks 5-6 ✓
- Deferred to later plans (correctly out of scope here): RepoFacts (Plan 3 Parsers), graph linking (Plan 4), API endpoints (Plan 5), ingest/SHA resolution (Plan 2).

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every run step shows the command and expected result.

**Type consistency:** `handler_ref`/`handlerRef`, `code_ref`/`codeRef`, `endpoint_id`/`endpointId`, `from_node`/`from`, `to_node`/`to` consistent across tasks and tests. `cache_key(project)` and `Cache.get/put` signatures match their tests. `ANALYZER_VERSION` is the only version source.
