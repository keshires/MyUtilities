# DocuProj Linker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Linker — join per-repo `RepoFacts` into a cross-repo `AnalysisModel` of endpoints + `Flow`s, using deterministic path-prefix matching, behind a pluggable `Resolver` seam so Claude-assisted resolution can drop in later.

**Architecture:** `link(facts, project, resolver)` collects all inbound `Endpoint`s and all UI `ConfigUrl` sources, then for each endpoint asks the `Resolver` to score each source→endpoint link. The shipped `DeterministicResolver` matches a config URL's path against an endpoint path (exact = 1.0, service-prefix = 0.5). Matches become a `Flow` (ui node → route node, `http` edge with confidence). A future `ClaudeResolver` implements the same `score(LinkQuery)` seam using the source code snippet.

**Tech Stack:** Python 3.12, pydantic v2, `urllib.parse` (stdlib), pytest. Tests use synthetic `RepoFacts` — offline, deterministic. No new dependencies, no API key.

---

## Roadmap context

**Plan 4 of the Phase-1 MVP vertical.** Consumes Plan 3's `RepoFacts`; produces the `AnalysisModel` (the §4 contract) that Plan 5 (API) serves and Plan 6 (Dashboard) renders. The Claude-assisted resolution the spec calls for (§3) is deferred behind the `Resolver` seam (user-chosen scope).

## File Structure

```
DocuProj/
  engine/
    linker.py          # url_path(), LinkQuery, Resolver protocol, DeterministicResolver, link()
  tests/
    test_linker.py     # url_path, resolver scoring, link() flow construction, resolver seam
```

`linker.py` is one module: the matching policy (`Resolver`) and the graph builder (`link`) live together because they change together. `link` depends only on Plan 1 models + Plan 3 `RepoFacts`.

---

### Task 1: `url_path()`, `LinkQuery`, and `DeterministicResolver`

**Files:**
- Create: `DocuProj/engine/linker.py`
- Test: `DocuProj/tests/test_linker.py`

`url_path` extracts the path from a config URL (absolute or relative). `LinkQuery` is the resolver's input (carries the source code ref so a Claude resolver can read the snippet). `DeterministicResolver.score` does exact/prefix matching.

- [ ] **Step 1: Write the failing test** — `DocuProj/tests/test_linker.py`

```python
from engine.linker import DeterministicResolver, LinkQuery, url_path
from engine.models import CodeRef, Endpoint


def _ref():
    return CodeRef(repo="r", file="f", line=1, snippet="s")


def _endpoint(path):
    return Endpoint(id=f"edfx-api:GET:{path}", repo="edfx-api", method="GET", path=path,
                    handler_ref=_ref(), language="python")


def test_url_path_absolute_and_relative():
    assert url_path("https://ci-api.edfx.moodysanalytics.net/edfx/v2") == "/edfx/v2"
    assert url_path("/1.0") == "/1.0"
    assert url_path("") == ""


def _query(source_path, endpoint):
    return LinkQuery(source_label="edfxApiV2Url", source_path=source_path, source_ref=_ref(), endpoint=endpoint)


def test_resolver_exact_match_is_full_confidence():
    r = DeterministicResolver()
    assert r.score(_query("/edfx/v2", _endpoint("/edfx/v2"))) == 1.0


def test_resolver_prefix_match_is_partial_confidence():
    r = DeterministicResolver()
    assert r.score(_query("/edfx/v2", _endpoint("/edfx/v2/tools/customPd"))) == 0.5


def test_resolver_no_match_returns_none():
    r = DeterministicResolver()
    assert r.score(_query("/edfx/v2", _endpoint("/other/y"))) is None


def test_resolver_ignores_root_or_empty_source():
    r = DeterministicResolver()
    assert r.score(_query("/", _endpoint("/edfx/v2/x"))) is None
    assert r.score(_query("", _endpoint("/edfx/v2/x"))) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_linker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.linker'`.

- [ ] **Step 3: Implement** — `DocuProj/engine/linker.py`

```python
"""Linker: join RepoFacts into a cross-repo AnalysisModel via a pluggable Resolver."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel

from engine.models import CodeRef, Endpoint


def url_path(url: str) -> str:
    """Path component of a config URL. Absolute -> its path; relative -> unchanged."""
    parts = urlsplit(url)
    if parts.scheme or parts.netloc:
        return parts.path
    return url


class LinkQuery(BaseModel):
    """A candidate link a Resolver scores: a UI source against one inbound endpoint."""

    source_label: str          # e.g. the endPointConfig key
    source_path: str           # URL path of the source ("" if unknown)
    source_ref: CodeRef        # where the source lives (snippet for a Claude resolver)
    endpoint: Endpoint


class Resolver(Protocol):
    def score(self, query: LinkQuery) -> float | None:
        """Confidence 0..1 that the source links to the endpoint, or None for no link."""
        ...


class DeterministicResolver:
    """Path matching: exact path == 1.0, service-prefix == 0.5, else no link."""

    def score(self, query: LinkQuery) -> float | None:
        source = query.source_path.rstrip("/")
        if not source:
            return None
        endpoint_path = query.endpoint.path
        if endpoint_path == query.source_path or endpoint_path == source:
            return 1.0
        if endpoint_path.startswith(source + "/"):
            return 0.5
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_linker.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add DocuProj/engine/linker.py DocuProj/tests/test_linker.py
git commit -m "feat(linker): add url_path, LinkQuery, and DeterministicResolver"
```

---

### Task 2: `link()` graph builder + exports

**Files:**
- Modify: `DocuProj/engine/linker.py`
- Modify: `DocuProj/engine/__init__.py`
- Test: `DocuProj/tests/test_linker.py` (append)

`link()` builds the `AnalysisModel`: every inbound endpoint is listed; each gets a `Flow` only if at least one source links to it. A pluggable `resolver` lets callers swap matching strategy (the Claude seam).

- [ ] **Step 1: Write the failing test** — append to `DocuProj/tests/test_linker.py`

```python
from engine.facts import ConfigUrl, RepoFacts
from engine.linker import link
from engine.models import Project, RepoRef


def _project():
    return Project(
        id="edfx-flow",
        name="EDFX Flow",
        repos=[
            RepoRef(url="u1", folder="edfx-app-ui", branch="main", sha="a"),
            RepoRef(url="u2", folder="edfx-api", branch="master", sha="b"),
        ],
    )


def _facts():
    ui = RepoFacts(
        repo="edfx-app-ui",
        language="typescript",
        config_urls=[ConfigUrl(key="edfxApiV2Url", url="https://h/edfx/v2", code_ref=_ref())],
    )
    api = RepoFacts(
        repo="edfx-api",
        language="python",
        endpoints=[_endpoint("/edfx/v2/tools/customPd"), _endpoint("/other/y")],
    )
    return [ui, api]


def test_link_builds_analysis_model():
    model = link(_facts(), _project())
    assert len(model.endpoints) == 2          # all inbound endpoints listed
    assert len(model.flows) == 1              # only the /edfx/v2 one is reachable
    flow = model.flows[0]
    assert flow.endpoint_id == "edfx-api:GET:/edfx/v2/tools/customPd"
    kinds = sorted(n.kind for n in flow.nodes)
    assert kinds == ["route", "ui"]
    ui_node = next(n for n in flow.nodes if n.kind == "ui")
    assert ui_node.label == "edfxApiV2Url"
    assert flow.edges[0].kind == "http"
    assert flow.edges[0].confidence == 0.5
    assert flow.edges[0].from_node == ui_node.id


def test_link_respects_custom_resolver_seam():
    class MatchAll:
        def score(self, query):
            return 1.0

    model = link(_facts(), _project(), resolver=MatchAll())
    assert len(model.flows) == 2              # every endpoint now links
    assert all(e.confidence == 1.0 for f in model.flows for e in f.edges)
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_linker.py -v`
Expected: FAIL with `ImportError: cannot import name 'link'`.

- [ ] **Step 3: Implement** — append to `DocuProj/engine/linker.py`

Add these imports to the existing import block at the top of `linker.py`:

```python
from engine.facts import RepoFacts
from engine.models import AnalysisModel, Flow, FlowEdge, FlowNode, Project
```

(The existing `from engine.models import CodeRef, Endpoint` line stays; or merge into the new `engine.models` import.)

Append the function:

```python
def link(
    facts: list[RepoFacts],
    project: Project,
    resolver: Resolver | None = None,
) -> AnalysisModel:
    resolver = resolver or DeterministicResolver()
    endpoints = [ep for f in facts for ep in f.endpoints]
    sources = [
        (f.repo, c.key, url_path(c.url), c.code_ref)
        for f in facts
        for c in f.config_urls
    ]
    flows: list[Flow] = []
    for ep in endpoints:
        route = FlowNode(
            id=f"route:{ep.id}",
            repo=ep.repo,
            label=f"{ep.method} {ep.path}",
            kind="route",
            code_ref=ep.handler_ref,
        )
        nodes: list[FlowNode] = []
        edges: list[FlowEdge] = []
        seen_ui: set[str] = set()
        for repo, label, spath, ref in sources:
            confidence = resolver.score(
                LinkQuery(source_label=label, source_path=spath, source_ref=ref, endpoint=ep)
            )
            if confidence is None:
                continue
            uid = f"ui:{repo}:{label}"
            if uid not in seen_ui:
                nodes.append(FlowNode(id=uid, repo=repo, label=label, kind="ui", code_ref=ref))
                seen_ui.add(uid)
            edges.append(FlowEdge(from_node=uid, to_node=route.id, kind="http", confidence=confidence))
        if edges:
            nodes.append(route)
            flows.append(Flow(endpoint_id=ep.id, nodes=nodes, edges=edges))
    return AnalysisModel(project=project, endpoints=endpoints, flows=flows)
```

Then add to `DocuProj/engine/__init__.py` — add this import after the `from engine.parsers import parse` line:

```python
from engine.linker import DeterministicResolver, LinkQuery, Resolver, link, url_path
```

And extend `__all__` with (alphabetical insertion):

```python
    "DeterministicResolver",
    "LinkQuery",
    "Resolver",
    "link",
    "url_path",
```

- [ ] **Step 4: Run the full test suite**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest -v`
Expected: PASS — Plan 1-3 (31) + Plan 4 (7) = 38 tests.

- [ ] **Step 5: Commit**

```bash
git add DocuProj/engine/linker.py DocuProj/engine/__init__.py DocuProj/tests/test_linker.py
git commit -m "feat(linker): add link() graph builder and public exports"
```

---

## Self-Review

**Spec coverage (Linker, §3 / §4):**
- `link(allRepoFacts) -> AnalysisModel` interface — Task 2 ✓
- Deterministic match first (path/prefix) — Task 1 `DeterministicResolver` ✓
- Confidence score on edges (1.0 exact, 0.5 service-prefix) — Tasks 1-2 ✓
- Front-end → backend link via same mechanism (UI config source → gateway route) — Task 2 ✓
- `Flow` with ui/route nodes + `http` edge (§4 FlowNode/FlowEdge kinds) — Task 2 ✓
- AnalysisModel lists all endpoints; flows only where reachable — Task 2 ✓
- Claude for ambiguous cases — deferred behind the `Resolver` seam (`score(LinkQuery)`), `LinkQuery.source_ref` carries the snippet a `ClaudeResolver` needs (user-chosen scope) ✓
- Deferred (correctly): real Claude wiring (later plan); intra-repo `calls` edges and `fn`/`outbound` node kinds (beyond first hop, YAGNI).

**Placeholder scan:** No TBD/TODO; all code complete; every run step has command + expected outcome.

**Type consistency:** `url_path(url)`, `LinkQuery{source_label, source_path, source_ref, endpoint}`, `Resolver.score(query) -> float | None`, `DeterministicResolver`, and `link(facts, project, resolver)` are referenced identically across tasks/tests. `link` reuses Plan 1 `FlowNode/FlowEdge/Flow/AnalysisModel` and Plan 3 `RepoFacts/ConfigUrl` exactly. Node ids `route:<id>` / `ui:<repo>:<label>` are consistent between builder and edge wiring.
