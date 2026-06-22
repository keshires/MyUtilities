# DocuProj Cross-Repo Depth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deepen flows beyond the first hop — extract Python outbound HTTP calls (`requests`/`httpx`/`aiohttp`/client wrappers) and generalize the Linker so an outbound call in one repo links to an inbound route in another, producing multi-repo chains where paths align.

**Architecture:** A new `extract_python_outbound()` finds `<client>.<verb>(target, …)` call sites; `parse()` now returns both inbound endpoints **and** outbound calls for Python repos. The Linker treats both UI `ConfigUrl`s and `OutboundCall`s as **link sources**, extracts a path from each (`target_path()` pulls a literal `/…` fragment), and matches it against endpoints in **other** repos via the existing `DeterministicResolver`. Sources with no literal path produce no edge (the accepted "partial" limit; precise resolution is deferred to the Claude Resolver seam).

**Tech Stack:** Python 3.12, tree-sitter (existing), pydantic v2, pytest. Tests use synthetic fixtures; validated against the 4 cloned EDFX repos.

---

## Roadmap context

**Plan 7** — extends Plan 3 (parsers) and Plan 4 (linker). Enables the multi-repo swimlane depth the design mockups show. Plan 8 (swimlane UI) renders whatever depth this produces. Precise gateway→downstream links remain deferred to the Claude Resolver (the seam from Plan 4).

## File Structure

```
DocuProj/
  engine/
    parsers/python_http.py     # extract_python_outbound()
    parsers/__init__.py        # parse(): python -> endpoints + outbound_calls
    linker.py                  # target_path(); link() sources = config + outbound, cross-repo
  tests/
    fixtures/py_http/client.py
    test_parser_python_http.py
    test_linker.py             # append cross-repo outbound tests
```

---

### Task 1: Python outbound-call extractor

**Files:**
- Create: `DocuProj/engine/parsers/python_http.py`
- Create: `DocuProj/tests/fixtures/py_http/client.py`
- Test: `DocuProj/tests/test_parser_python_http.py`

Matches `call` nodes whose function is `<obj>.<verb>` with `verb` in the HTTP set and `obj` text containing a client hint (`requests`/`httpx`/`aiohttp`/`session`/`client`/`http`). Captures method + first-arg text (the target) + code ref. Grounded in `edfx-api`'s real `session.post(url, …)` / `requests.get(url)` / `httpx.get(self.sso_url + '/auth/certs')`.

- [ ] **Step 1: Create the fixture** — `DocuProj/tests/fixtures/py_http/client.py`

```python
import httpx
import requests


def call_resolve():
    # literal path -> linkable
    return requests.post("/entity/v1/resolve", json={})


def call_var(url):
    # bare variable target -> not linkable (partial)
    return requests.get(url)


async def call_session(session, base):
    return await session.get(base + "/financials/client/v1/ratios")


def not_http(d):
    # client hint absent -> ignored
    return d.get("key")
```

- [ ] **Step 2: Write the failing test** — `DocuProj/tests/test_parser_python_http.py`

```python
from pathlib import Path

from engine.parsers.python_http import extract_python_outbound

_FIX = Path(__file__).resolve().parent / "fixtures" / "py_http"


def test_extract_python_outbound():
    calls = extract_python_outbound(_FIX, repo="edfx-api")
    methods = sorted(c.method for c in calls)
    # POST (requests), GET (requests var), GET (session) — not_http excluded
    assert methods == ["GET", "GET", "POST"]
    post = next(c for c in calls if c.method == "POST")
    assert "/entity/v1/resolve" in post.target
    assert post.code_ref.file == "client.py"
    assert post.code_ref.line >= 1
```

- [ ] **Step 3: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_parser_python_http.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.parsers.python_http'`.

- [ ] **Step 4: Implement** — `DocuProj/engine/parsers/python_http.py`

```python
"""Extract Python outbound HTTP calls: <client>.<verb>(target, ...)."""

from __future__ import annotations

from pathlib import Path

from engine.facts import OutboundCall
from engine.models import CodeRef
from engine.parsers._support import python_parser, text, walk

_VERBS = {"get", "post", "put", "delete", "patch"}
_CLIENT_HINTS = ("requests", "httpx", "aiohttp", "session", "client", "http")


def extract_python_outbound(repo_path, repo: str) -> list[OutboundCall]:
    parser = python_parser()
    out: list[OutboundCall] = []
    repo_root = Path(repo_path)
    for py in sorted(repo_root.rglob("*.py")):
        source = py.read_bytes()
        root = parser.parse(source).root_node
        rel = py.relative_to(repo_root).as_posix()
        lines = source.decode("utf-8", "replace").splitlines()
        for node in walk(root):
            if node.type != "call":
                continue
            fn = node.child_by_field_name("function")
            if fn is None or fn.type != "attribute":
                continue
            obj = fn.child_by_field_name("object")
            attr = fn.child_by_field_name("attribute")
            if obj is None or attr is None:
                continue
            verb = text(attr)
            if verb not in _VERBS or not any(h in text(obj).lower() for h in _CLIENT_HINTS):
                continue
            target = ""
            args = node.child_by_field_name("arguments")
            if args is not None:
                reals = [c for c in args.children if c.type not in ("(", ")", ",")]
                if reals:
                    target = text(reals[0])
            row = node.start_point[0]
            snippet = lines[row].strip() if row < len(lines) else ""
            out.append(
                OutboundCall(
                    method=verb.upper(),
                    target=target,
                    code_ref=CodeRef(repo=repo, file=rel, line=row + 1, snippet=snippet),
                )
            )
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_parser_python_http.py -v`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
git add DocuProj/engine/parsers/python_http.py DocuProj/tests/fixtures/py_http/client.py DocuProj/tests/test_parser_python_http.py
git commit -m "feat(parsers): add Python outbound HTTP-call extractor"
```

---

### Task 2: `parse()` returns outbound calls for Python repos

**Files:**
- Modify: `DocuProj/engine/parsers/__init__.py`
- Test: `DocuProj/tests/test_parser_python.py` (append)

- [ ] **Step 1: Write the failing test** — append to `DocuProj/tests/test_parser_python.py`

```python
def test_parse_python_includes_outbound():
    # the py_http fixture has outbound calls; FastAPI fixture has none
    facts = parse(Path(__file__).resolve().parent / "fixtures" / "py_http", "python", repo="edfx-api")
    assert len(facts.outbound_calls) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_parser_python.py::test_parse_python_includes_outbound -v`
Expected: FAIL — `outbound_calls` is empty (currently 0).

- [ ] **Step 3: Implement** — edit `DocuProj/engine/parsers/__init__.py`

Add the import:

```python
from engine.parsers.python_http import extract_python_outbound
```

Change the python branch of `parse()` from:

```python
    if lang == "python":
        return RepoFacts(
            repo=repo, language="python", endpoints=extract_fastapi_routes(repo_path, repo)
        )
```

to:

```python
    if lang == "python":
        return RepoFacts(
            repo=repo,
            language="python",
            endpoints=extract_fastapi_routes(repo_path, repo),
            outbound_calls=extract_python_outbound(repo_path, repo),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_parser_python.py -v`
Expected: PASS (all python parser tests, including the new one).

- [ ] **Step 5: Commit**

```bash
git add DocuProj/engine/parsers/__init__.py DocuProj/tests/test_parser_python.py
git commit -m "feat(parsers): parse() returns Python outbound calls alongside routes"
```

---

### Task 3: Linker — `target_path()` + cross-repo outbound→inbound links

**Files:**
- Modify: `DocuProj/engine/linker.py`
- Test: `DocuProj/tests/test_linker.py` (append)

Generalize `link()` so both `ConfigUrl`s (kind `ui`) and `OutboundCall`s (kind `outbound`) are link sources. A source only links to endpoints in a **different repo**. `target_path()` extracts a literal `/…` fragment from an outbound target (bare variables yield `""` → no edge).

- [ ] **Step 1: Write the failing test** — append to `DocuProj/tests/test_linker.py`

```python
from engine.linker import target_path


def test_target_path_extracts_literal_only():
    assert target_path("'/entity/v1/resolve'") == "/entity/v1/resolve"
    assert target_path("base + '/financials/client/v1/ratios'") == "/financials/client/v1/ratios"
    assert target_path("url") == ""  # bare variable -> no path


def test_link_connects_outbound_to_downstream_route():
    from engine.facts import OutboundCall, RepoFacts

    gateway = RepoFacts(
        repo="edfx-api",
        language="python",
        endpoints=[_endpoint("/edfx/v2/x")],  # gateway's own route
        outbound_calls=[
            OutboundCall(method="POST", target="'/entity/v1/resolve'", code_ref=_ref())
        ],
    )
    entity = RepoFacts(
        repo="edfx_entity_api",
        language="python",
        endpoints=[Endpoint(id="edfx_entity_api:POST:/entity/v1/resolve", repo="edfx_entity_api",
                            method="POST", path="/entity/v1/resolve", handler_ref=_ref(), language="python")],
    )
    project = Project(id="p", name="p", repos=[
        RepoRef(url="a", folder="edfx-api", branch="master", sha="1"),
        RepoRef(url="b", folder="edfx_entity_api", branch="main", sha="2"),
    ])
    model = link([gateway, entity], project)
    # the downstream route is reachable via the gateway's outbound call
    flow = next(f for f in model.flows if f.endpoint_id == "edfx_entity_api:POST:/entity/v1/resolve")
    kinds = sorted(n.kind for n in flow.nodes)
    assert kinds == ["outbound", "route"]
    assert flow.edges[0].kind == "http"
    # gateway's own /edfx/v2/x has no inbound source -> no flow
    assert not any(f.endpoint_id == "edfx-api:GET:/edfx/v2/x" for f in model.flows)
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_linker.py -v`
Expected: FAIL with `ImportError: cannot import name 'target_path'`.

- [ ] **Step 3: Implement** — edit `DocuProj/engine/linker.py`

Add `import re` to the top imports. Add `target_path` after `url_path`:

```python
_PATH_LITERAL = re.compile(r"""['"`](/[^'"`]*)['"`]""")


def target_path(target: str) -> str:
    """Extract a literal path fragment from an outbound target expression, else ''."""
    m = _PATH_LITERAL.search(target)
    return m.group(1) if m else ""
```

Replace the body of `link()` with the generalized source handling:

```python
def link(
    facts: list[RepoFacts],
    project: Project,
    resolver: Resolver | None = None,
) -> AnalysisModel:
    resolver = resolver or DeterministicResolver()
    endpoints = [ep for f in facts for ep in f.endpoints]

    # Sources: UI config URLs (kind "ui") + outbound HTTP calls (kind "outbound").
    sources = []
    for f in facts:
        for c in f.config_urls:
            sources.append((f.repo, "ui", c.key, url_path(c.url), c.code_ref))
        for o in f.outbound_calls:
            sources.append((f.repo, "outbound", f"{o.method} {o.target}"[:48], target_path(o.target), o.code_ref))

    flows: list[Flow] = []
    for ep in endpoints:
        route = FlowNode(
            id=f"route:{ep.id}", repo=ep.repo, label=f"{ep.method} {ep.path}",
            kind="route", code_ref=ep.handler_ref,
        )
        nodes: list[FlowNode] = []
        edges: list[FlowEdge] = []
        seen: set[str] = set()
        for src_repo, kind, label, spath, ref in sources:
            if src_repo == ep.repo:
                continue  # cross-repo links only
            confidence = resolver.score(
                LinkQuery(source_label=label, source_path=spath, source_ref=ref, endpoint=ep)
            )
            if confidence is None:
                continue
            nid = f"{kind}:{src_repo}:{label}"
            if nid not in seen:
                nodes.append(FlowNode(id=nid, repo=src_repo, label=label, kind=kind, code_ref=ref))
                seen.add(nid)
            edges.append(FlowEdge(from_node=nid, to_node=route.id, kind="http", confidence=confidence))
        if edges:
            nodes.append(route)
            flows.append(Flow(endpoint_id=ep.id, nodes=nodes, edges=edges))
    return AnalysisModel(project=project, endpoints=endpoints, flows=flows)
```

Then export `target_path` — add it to the `from engine.linker import …` line in `DocuProj/engine/__init__.py` and to `__all__`.

- [ ] **Step 4: Run the full test suite**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest -q`
Expected: PASS — existing 55 + Plan 7 new (≈4) = ~59. (Existing UI→gateway flows still link: UI repo ≠ gateway repo, config path matches.)

- [ ] **Step 5: Commit**

```bash
git add DocuProj/engine/linker.py DocuProj/engine/__init__.py DocuProj/tests/test_linker.py
git commit -m "feat(linker): cross-repo outbound->inbound links via target_path"
```

---

### Task 4: Real-repo validation (4 EDFX repos)

**Files:** none (verification only)

- [ ] **Step 1: Run full suite** — `.\.venv\Scripts\pytest -q` → all pass.

- [ ] **Step 2: Analyze the 4 cloned repos** and report depth:

```python
from engine import parse, link, Project, RepoRef
WS = ".workspace/edfx-flow"
specs = [("edfx-app-ui","angular","main"),("edfx-api","python","master"),
         ("edfx_entity_api","python","main"),("edfx-client-financials-api","python","main")]
facts = [parse(f"{WS}/{f}", lang, repo=f) for f,lang,_ in specs]
project = Project(id="edfx-flow", name="EDFX Flow",
    repos=[RepoRef(url="x", folder=f, branch=b, sha=f) for f,_,b in specs])
model = link(facts, project)
print("endpoints:", len(model.endpoints), "flows:", len(model.flows))
repos_in_flows = {n.repo for fl in model.flows for n in fl.nodes}
print("repos appearing in flows:", sorted(repos_in_flows))
```

Expected: endpoint count grows well beyond 87 (entity_api + financials-api routes added); some flows now include `outbound` nodes from `edfx-api` linking to downstream routes (sparse, where literal paths align).

---

## Addendum — Tasks 5–7: constant resolution (added after Task 4 validation)

Task 4 revealed the EDFX services build route paths and outbound targets from **module-level named constants** (`CLIENT_FINANCIALS_CONTEXT`, `VERSION_1`, …), so literal matching found 0 links and downstream paths were mis-extracted. Fix deterministically:

- **Task 5 — `engine/parsers/_consts.py`:** `build_const_map(repo_root)` scans module-level `NAME = "literal"` assignments repo-wide; `resolve_expr(node, consts)` resolves a string / identifier / `+`-concatenation node to a string (else `None`). TDD with a small fixture.
- **Task 6 — wire into `python_fastapi.py`:** build the const map per repo; when a router `prefix` or decorator path is an identifier/concatenation (not a string), resolve it via the map. Fixture: a router whose prefix + path are constants → resolves to the real path.
- **Task 7 — wire into `python_http.py` + re-validate:** resolve outbound targets through the const map too; then re-run the 4-repo analysis. Expect downstream route paths now correct, and UI per-service config URLs (`entitySearchApiUrl`, `clientFinancialsApiUrl`) prefix-matching downstream routes → cross-repo flows into `edfx_entity_api` / `edfx-client-financials-api`.

## Self-Review

**Spec coverage (§3 Linker — cross-repo join):**
- Outbound HTTP calls extracted for Python (not just Angular) — Task 1 ✓
- `parse()` emits outbound calls for Python repos — Task 2 ✓
- Cross-repo outbound→inbound matching (deterministic, literal-path) — Task 3 ✓
- Cross-repo-only guard (no intra-repo self-links) — Task 3 ✓
- `outbound` node kind used (§4) — Task 3 ✓
- Partial by design: bare-variable targets yield no edge; precise resolution deferred to the Claude Resolver seam — documented ✓

**Placeholder scan:** No TBD/TODO; all code complete; run steps show commands + expected outcomes.

**Type consistency:** `extract_python_outbound(repo_path, repo)`, `target_path(target)`, and the generalized `link()` reuse Plan 1/3/4 types exactly (`OutboundCall`, `RepoFacts`, `FlowNode.kind` ∈ ui|route|fn|outbound, `LinkQuery`). Node id scheme `"{kind}:{repo}:{label}"` is consistent between node creation and edge `from_node`.
