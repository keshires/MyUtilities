# DocuProj Parsers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the two tree-sitter extractors the MVP's first hop needs — Python/FastAPI inbound routes (`edfx-api`) and Angular/TypeScript outbound HTTP calls + `endPointConfig` URL map (`edfx-app-ui`) — exposed through one `parse(repo_path, language) -> RepoFacts`.

**Architecture:** tree-sitter parses source deterministically; small node-traversal extractors (no query DSL, for version stability) pull structural facts. The Python extractor discovers `APIRouter(prefix=…)` assignments then matches `@<var>.<verb>("path")` decorators → `Endpoint`. The TS extractor pulls `endPointConfig` key→URL pairs and `this.http.<verb>(…)` call sites → `ConfigUrl` / `OutboundCall`. Cross-repo URL resolution is **out of scope** (Linker, Plan 4).

**Tech Stack:** Python 3.12, pydantic v2, `tree-sitter` 0.25, `tree-sitter-python` 0.25, `tree-sitter-typescript` 0.23, pytest. Tests run against small committed fixtures that mirror the real EDFX patterns (verified §12 of the design spec) — offline, no `.workspace` dependency.

---

## Roadmap context

**Plan 3 of the Phase-1 MVP vertical.** Consumes Plan 2's resolved checkouts; produces `RepoFacts` (the inbound endpoints + outbound calls) that Plan 4 (Linker) joins into a cross-repo `Flow`. API verified live (tree-sitter node fields confirmed against 0.25 before writing this plan).

## File Structure

```
DocuProj/
  requirements.txt                       # + tree-sitter, tree-sitter-python, tree-sitter-typescript
  engine/
    facts.py                             # RepoFacts, OutboundCall, ConfigUrl
    parsers/
      __init__.py                        # parse() dispatcher
      _support.py                        # cached parsers, walk(), text(), str_literal()
      python_fastapi.py                  # extract_fastapi_routes()
      ts_angular.py                      # extract_angular_outbound()
  tests/
    fixtures/
      py_fastapi/sample_router.py
      ts_angular/environment.dev.ts
      ts_angular/entity.service.ts
    test_facts.py
    test_parser_python.py
    test_parser_ts.py
```

---

### Task 1: tree-sitter deps + `_support.py`

**Files:**
- Modify: `DocuProj/requirements.txt`
- Create: `DocuProj/engine/parsers/__init__.py` (empty for now)
- Create: `DocuProj/engine/parsers/_support.py`
- Test: `DocuProj/tests/test_parser_python.py` (support smoke only, expanded in Task 3)

- [ ] **Step 1: Add deps** — append to `DocuProj/requirements.txt`

```text
tree-sitter>=0.23,<0.26
tree-sitter-python>=0.23,<0.26
tree-sitter-typescript>=0.23,<0.26
```

- [ ] **Step 2: Install**

Run (from `DocuProj/`): `.\.venv\Scripts\pip install -r requirements.txt`
Expected: tree-sitter packages install.

- [ ] **Step 3: Write the failing test** — `DocuProj/tests/test_parser_python.py`

```python
from engine.parsers._support import python_parser, str_literal, text, walk


def test_python_parser_parses_and_helpers_work():
    parser = python_parser()
    tree = parser.parse(b'x = "hello"\n')
    root = tree.root_node
    assert root.type == "module"
    strings = [n for n in walk(root) if n.type == "string"]
    assert len(strings) == 1
    assert str_literal(strings[0]) == "hello"
    assert text(strings[0]).startswith('"')
```

- [ ] **Step 4: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_parser_python.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.parsers'`.

- [ ] **Step 5: Implement** — create `DocuProj/engine/parsers/__init__.py` (empty):

```python
```

Create `DocuProj/engine/parsers/_support.py`:

```python
"""Shared tree-sitter setup and node helpers (node-traversal API, version-stable)."""

from __future__ import annotations

from functools import lru_cache

import tree_sitter_python as tsp
import tree_sitter_typescript as tst
from tree_sitter import Language, Parser


@lru_cache(maxsize=1)
def python_parser() -> Parser:
    return Parser(Language(tsp.language()))


@lru_cache(maxsize=1)
def ts_parser() -> Parser:
    return Parser(Language(tst.language_typescript()))


def walk(node):
    """Yield node and all descendants, depth-first."""
    yield node
    for child in node.children:
        yield from walk(child)


def text(node) -> str:
    return node.text.decode("utf-8", "replace")


def str_literal(node) -> str:
    """Literal value of a string node: prefer the content child, else strip quotes."""
    for child in node.children:
        if child.type in ("string_content", "string_fragment"):
            return text(child)
    raw = text(node)
    if len(raw) >= 2 and raw[0] in "\"'`" and raw[-1] in "\"'`":
        return raw[1:-1]
    return raw
```

- [ ] **Step 6: Run test to verify it passes**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_parser_python.py -v`
Expected: PASS (1 passed).

- [ ] **Step 7: Commit**

```bash
git add DocuProj/requirements.txt DocuProj/engine/parsers/__init__.py DocuProj/engine/parsers/_support.py DocuProj/tests/test_parser_python.py
git commit -m "feat(parsers): add tree-sitter deps and _support helpers"
```

---

### Task 2: `facts.py` models

**Files:**
- Create: `DocuProj/engine/facts.py`
- Test: `DocuProj/tests/test_facts.py`

`RepoFacts` is the parser output: inbound `endpoints` (reuses Plan 1 `Endpoint`), plus `outbound_calls` and `config_urls`.

- [ ] **Step 1: Write the failing test** — `DocuProj/tests/test_facts.py`

```python
from engine.facts import ConfigUrl, OutboundCall, RepoFacts
from engine.models import CodeRef


def test_repofacts_defaults_empty():
    facts = RepoFacts(repo="edfx-api", language="python")
    assert facts.endpoints == []
    assert facts.outbound_calls == []
    assert facts.config_urls == []


def test_outbound_and_config_round_trip():
    ref = CodeRef(repo="edfx-app-ui", file="a.ts", line=3, snippet="this.http.get(url)")
    call = OutboundCall(method="GET", target="`${base}/x`", code_ref=ref)
    cfg = ConfigUrl(key="edfxApiV2Url", url="https://h/edfx/v2", code_ref=ref)
    facts = RepoFacts(repo="edfx-app-ui", language="typescript", outbound_calls=[call], config_urls=[cfg])
    assert RepoFacts.model_validate(facts.model_dump()) == facts
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_facts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.facts'`.

- [ ] **Step 3: Implement** — `DocuProj/engine/facts.py`

```python
"""Parser output: per-repo structural facts (the Linker's input)."""

from __future__ import annotations

from pydantic import BaseModel

from engine.models import CodeRef, Endpoint


class OutboundCall(BaseModel):
    method: str
    target: str  # raw first-arg expression text (URL literal, template, or variable)
    code_ref: CodeRef


class ConfigUrl(BaseModel):
    key: str
    url: str
    code_ref: CodeRef


class RepoFacts(BaseModel):
    repo: str
    language: str
    endpoints: list[Endpoint] = []
    outbound_calls: list[OutboundCall] = []
    config_urls: list[ConfigUrl] = []
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_facts.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add DocuProj/engine/facts.py DocuProj/tests/test_facts.py
git commit -m "feat(facts): add RepoFacts, OutboundCall, ConfigUrl models"
```

---

### Task 3: Python/FastAPI route extractor

**Files:**
- Create: `DocuProj/engine/parsers/python_fastapi.py`
- Create: `DocuProj/tests/fixtures/py_fastapi/sample_router.py`
- Modify: `DocuProj/tests/test_parser_python.py` (append)

Mirrors the real pattern: `x_router = APIRouter(prefix="/entities")` + `@x_router.get("/{id}")` with the handler `def` below. Full path = prefix + decorator arg.

- [ ] **Step 1: Create the fixture** — `DocuProj/tests/fixtures/py_fastapi/sample_router.py`

```python
from fastapi import APIRouter

entity_router = APIRouter(prefix="/entities")


@entity_router.get("/{id}")
async def get_entity(id: str):
    return {"id": id}


@entity_router.post("")
async def create_entity():
    return {}


health_router = APIRouter()


@health_router.get("/health")
def health():
    return "ok"
```

- [ ] **Step 2: Write the failing test** — append to `DocuProj/tests/test_parser_python.py`

```python
from pathlib import Path

from engine.parsers.python_fastapi import extract_fastapi_routes

_FIX = Path(__file__).resolve().parent / "fixtures" / "py_fastapi"


def test_extract_fastapi_routes():
    eps = extract_fastapi_routes(_FIX, repo="edfx-api")
    routes = {(e.method, e.path) for e in eps}
    assert ("GET", "/entities/{id}") in routes
    assert ("POST", "/entities") in routes  # prefix + "" decorator path
    assert ("GET", "/health") in routes     # router with no prefix
    by_path = {e.path: e for e in eps}
    ep = by_path["/entities/{id}"]
    assert ep.language == "python"
    assert ep.handler_ref.file == "sample_router.py"
    assert ep.handler_ref.line >= 1
    assert "get_entity" in ep.handler_ref.snippet
```

- [ ] **Step 3: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_parser_python.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.parsers.python_fastapi'`.

- [ ] **Step 4: Implement** — `DocuProj/engine/parsers/python_fastapi.py`

```python
"""Extract FastAPI inbound routes: APIRouter(prefix=...) + @<var>.<verb>("path")."""

from __future__ import annotations

from pathlib import Path

from engine.models import CodeRef, Endpoint
from engine.parsers._support import python_parser, str_literal, text, walk

_VERBS = {"get", "post", "put", "delete", "patch"}


def _router_prefixes(root) -> dict[str, str]:
    """Map each `x = APIRouter(prefix="...")` variable to its prefix ("" if none)."""
    prefixes: dict[str, str] = {}
    for node in walk(root):
        if node.type != "assignment":
            continue
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None or right.type != "call":
            continue
        fn = right.child_by_field_name("function")
        if fn is None or text(fn) != "APIRouter":
            continue
        prefix = ""
        args = right.child_by_field_name("arguments")
        if args is not None:
            for arg in args.children:
                if arg.type != "keyword_argument":
                    continue
                name = arg.child_by_field_name("name")
                value = arg.child_by_field_name("value")
                if name is not None and value is not None and text(name) == "prefix":
                    prefix = str_literal(value)
        prefixes[text(left)] = prefix
    return prefixes


def _decorator_route(dec, prefixes):
    """Return (METHOD, full_path) for a matching @<router>.<verb>("path") decorator."""
    calls = [c for c in dec.children if c.type == "call"]
    if not calls:
        return None
    call = calls[0]
    fn = call.child_by_field_name("function")
    if fn is None or fn.type != "attribute":
        return None
    obj = fn.child_by_field_name("object")
    attr = fn.child_by_field_name("attribute")
    if obj is None or attr is None:
        return None
    router, verb = text(obj), text(attr)
    if router not in prefixes or verb not in _VERBS:
        return None
    path = ""
    args = call.child_by_field_name("arguments")
    if args is not None:
        for a in args.children:
            if a.type == "string":
                path = str_literal(a)
                break
    full = prefixes[router] + path
    return verb.upper(), (full or "/")


def _function_definition(decorated):
    fn = decorated.child_by_field_name("definition")
    if fn is not None and fn.type == "function_definition":
        return fn
    for child in decorated.children:
        if child.type == "function_definition":
            return child
    return None


def extract_fastapi_routes(repo_path, repo: str) -> list[Endpoint]:
    repo_root = Path(repo_path)
    parser = python_parser()
    endpoints: list[Endpoint] = []
    for py in sorted(repo_root.rglob("*.py")):
        source = py.read_bytes()
        root = parser.parse(source).root_node
        prefixes = _router_prefixes(root)
        if not prefixes:
            continue
        rel = py.relative_to(repo_root).as_posix()
        lines = source.decode("utf-8", "replace").splitlines()
        for node in walk(root):
            if node.type != "decorated_definition":
                continue
            fn_def = _function_definition(node)
            if fn_def is None:
                continue
            route = None
            for dec in node.children:
                if dec.type == "decorator":
                    route = _decorator_route(dec, prefixes)
                    if route:
                        break
            if route is None:
                continue
            method, path = route
            row = fn_def.start_point[0]
            snippet = lines[row].strip() if row < len(lines) else ""
            ref = CodeRef(repo=repo, file=rel, line=row + 1, snippet=snippet)
            endpoints.append(
                Endpoint(
                    id=f"{repo}:{method}:{path}",
                    repo=repo,
                    method=method,
                    path=path,
                    handler_ref=ref,
                    language="python",
                )
            )
    return endpoints
```

- [ ] **Step 5: Run test to verify it passes**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_parser_python.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add DocuProj/engine/parsers/python_fastapi.py DocuProj/tests/fixtures/py_fastapi/sample_router.py DocuProj/tests/test_parser_python.py
git commit -m "feat(parsers): add FastAPI route extractor"
```

---

### Task 4: TS/Angular `endPointConfig` extractor

**Files:**
- Create: `DocuProj/engine/parsers/ts_angular.py`
- Create: `DocuProj/tests/fixtures/ts_angular/environment.dev.ts`
- Create: `DocuProj/tests/test_parser_ts.py`

Pulls the `endPointConfig: { key: 'url' }` map from `environment.*.ts`. (Outbound calls added in Task 5.)

- [ ] **Step 1: Create the fixture** — `DocuProj/tests/fixtures/ts_angular/environment.dev.ts`

```typescript
export const environment = {
  production: false,
  endPointConfig: {
    endpointVersion: '/1.0',
    edfxApiV2Url: 'https://api.example.net/edfx/v2',
    entitySearchApiUrl: 'https://api.example.net/entity/v1',
  },
};
```

- [ ] **Step 2: Write the failing test** — `DocuProj/tests/test_parser_ts.py`

```python
from pathlib import Path

from engine.parsers.ts_angular import extract_angular_outbound

_FIX = Path(__file__).resolve().parent / "fixtures" / "ts_angular"


def test_extract_config_urls():
    _outbound, configs = extract_angular_outbound(_FIX, repo="edfx-app-ui")
    by_key = {c.key: c.url for c in configs}
    assert by_key["edfxApiV2Url"] == "https://api.example.net/edfx/v2"
    assert by_key["entitySearchApiUrl"] == "https://api.example.net/entity/v1"
    cfg = next(c for c in configs if c.key == "edfxApiV2Url")
    assert cfg.code_ref.file == "environment.dev.ts"
    assert cfg.code_ref.line >= 1
```

- [ ] **Step 3: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_parser_ts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.parsers.ts_angular'`.

- [ ] **Step 4: Implement** — `DocuProj/engine/parsers/ts_angular.py`

```python
"""Extract Angular outbound facts: endPointConfig URL map + this.http.<verb>() calls."""

from __future__ import annotations

from pathlib import Path

from engine.facts import ConfigUrl, OutboundCall
from engine.models import CodeRef
from engine.parsers._support import str_literal, text, ts_parser, walk

_VERBS = {"get", "post", "put", "delete", "patch"}


def _config_urls(root, repo, rel, lines) -> list[ConfigUrl]:
    out: list[ConfigUrl] = []
    for node in walk(root):
        if node.type != "pair":
            continue
        key = node.child_by_field_name("key")
        value = node.child_by_field_name("value")
        if key is None or value is None or text(key) != "endPointConfig" or value.type != "object":
            continue
        for entry in walk(value):
            if entry.type != "pair":
                continue
            k = entry.child_by_field_name("key")
            v = entry.child_by_field_name("value")
            if k is None or v is None or v.type != "string":
                continue
            row = entry.start_point[0]
            snippet = lines[row].strip() if row < len(lines) else ""
            out.append(
                ConfigUrl(
                    key=text(k),
                    url=str_literal(v),
                    code_ref=CodeRef(repo=repo, file=rel, line=row + 1, snippet=snippet),
                )
            )
        break  # first endPointConfig only
    return out


def extract_angular_outbound(repo_path, repo: str):
    repo_root = Path(repo_path)
    parser = ts_parser()
    outbound: list[OutboundCall] = []
    configs: list[ConfigUrl] = []
    for ts in sorted(repo_root.rglob("*.ts")):
        if ts.name.endswith(".d.ts"):
            continue
        source = ts.read_text(encoding="utf-8", errors="replace")
        root = parser.parse(source.encode("utf-8")).root_node
        rel = ts.relative_to(repo_root).as_posix()
        lines = source.splitlines()
        configs.extend(_config_urls(root, repo, rel, lines))
    return outbound, configs
```

- [ ] **Step 5: Run test to verify it passes**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_parser_ts.py -v`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
git add DocuProj/engine/parsers/ts_angular.py DocuProj/tests/fixtures/ts_angular/environment.dev.ts DocuProj/tests/test_parser_ts.py
git commit -m "feat(parsers): add Angular endPointConfig extractor"
```

---

### Task 5: TS/Angular outbound `this.http.<verb>()` extractor

**Files:**
- Modify: `DocuProj/engine/parsers/ts_angular.py`
- Create: `DocuProj/tests/fixtures/ts_angular/entity.service.ts`
- Modify: `DocuProj/tests/test_parser_ts.py` (append)

Captures `this.http.<verb>(target, …)` call sites (target = raw first-arg text). Matches member expressions whose object contains `http`.

- [ ] **Step 1: Create the fixture** — `DocuProj/tests/fixtures/ts_angular/entity.service.ts`

```typescript
import { HttpClient } from '@angular/common/http';

export class EntityService {
  private base = 'https://api.example.net/edfx/v2';

  constructor(private http: HttpClient) {}

  getEntity(id: string) {
    return this.http.get(`${this.base}/entities/${id}`);
  }

  createEntity(body: any) {
    return this.http.post<Entity>(this.base + '/entities', body);
  }
}
```

- [ ] **Step 2: Write the failing test** — append to `DocuProj/tests/test_parser_ts.py`

```python
def test_extract_outbound_calls():
    outbound, _configs = extract_angular_outbound(_FIX, repo="edfx-app-ui")
    methods = sorted(c.method for c in outbound)
    assert methods == ["GET", "POST"]
    get_call = next(c for c in outbound if c.method == "GET")
    assert "entities" in get_call.target
    assert get_call.code_ref.file == "entity.service.ts"
    assert get_call.code_ref.line >= 1
```

- [ ] **Step 3: Run test to verify it fails**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_parser_ts.py::test_extract_outbound_calls -v`
Expected: FAIL — `outbound` is empty (assert on methods fails).

- [ ] **Step 4: Implement** — add to `DocuProj/engine/parsers/ts_angular.py`

Add the `_outbound_calls` function (place it above `extract_angular_outbound`):

```python
def _outbound_calls(root, repo, rel, lines) -> list[OutboundCall]:
    out: list[OutboundCall] = []
    for node in walk(root):
        if node.type != "call_expression":
            continue
        fn = node.child_by_field_name("function")
        if fn is None or fn.type != "member_expression":
            continue
        obj = fn.child_by_field_name("object")
        prop = fn.child_by_field_name("property")
        if obj is None or prop is None:
            continue
        verb = text(prop)
        if verb not in _VERBS or "http" not in text(obj).lower():
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

Then wire it into the loop in `extract_angular_outbound` — change:

```python
        lines = source.splitlines()
        configs.extend(_config_urls(root, repo, rel, lines))
```

to:

```python
        lines = source.splitlines()
        outbound.extend(_outbound_calls(root, repo, rel, lines))
        configs.extend(_config_urls(root, repo, rel, lines))
```

- [ ] **Step 5: Run test to verify it passes**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_parser_ts.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add DocuProj/engine/parsers/ts_angular.py DocuProj/tests/fixtures/ts_angular/entity.service.ts DocuProj/tests/test_parser_ts.py
git commit -m "feat(parsers): add Angular this.http outbound-call extractor"
```

---

### Task 6: `parse()` dispatcher + exports

**Files:**
- Modify: `DocuProj/engine/parsers/__init__.py`
- Modify: `DocuProj/engine/__init__.py`
- Test: `DocuProj/tests/test_parser_python.py` and `tests/test_parser_ts.py` (append dispatcher tests)

- [ ] **Step 1: Write the failing tests**

Append to `DocuProj/tests/test_parser_python.py`:

```python
from engine.parsers import parse


def test_parse_dispatches_python():
    facts = parse(_FIX, "python", repo="edfx-api")
    assert facts.language == "python"
    assert facts.repo == "edfx-api"
    assert len(facts.endpoints) == 3
    assert facts.outbound_calls == []
```

Append to `DocuProj/tests/test_parser_ts.py`:

```python
from engine.parsers import parse


def test_parse_dispatches_typescript():
    facts = parse(_FIX, "angular", repo="edfx-app-ui")
    assert facts.language == "typescript"
    assert len(facts.outbound_calls) == 2
    assert len(facts.config_urls) == 3
    assert facts.endpoints == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest tests/test_parser_python.py tests/test_parser_ts.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse' from 'engine.parsers'`.

- [ ] **Step 3: Implement** — set `DocuProj/engine/parsers/__init__.py`:

```python
"""Parser dispatch: source tree + language -> RepoFacts."""

from __future__ import annotations

from pathlib import Path

from engine.facts import RepoFacts
from engine.parsers.python_fastapi import extract_fastapi_routes
from engine.parsers.ts_angular import extract_angular_outbound


def parse(repo_path, language: str, repo: str | None = None) -> RepoFacts:
    repo = repo or Path(repo_path).name
    lang = language.lower()
    if lang == "python":
        return RepoFacts(
            repo=repo, language="python", endpoints=extract_fastapi_routes(repo_path, repo)
        )
    if lang in ("typescript", "angular", "ts", "tsx"):
        outbound, configs = extract_angular_outbound(repo_path, repo)
        return RepoFacts(
            repo=repo, language="typescript", outbound_calls=outbound, config_urls=configs
        )
    raise ValueError(f"unsupported language: {language}")


__all__ = ["parse"]
```

Then add to `DocuProj/engine/__init__.py` — add this import after the `from engine.ingest import …` line:

```python
from engine.facts import ConfigUrl, OutboundCall, RepoFacts
from engine.parsers import parse
```

And extend `__all__` with (alphabetical insertion):

```python
    "ConfigUrl",
    "OutboundCall",
    "RepoFacts",
    "parse",
```

- [ ] **Step 4: Run the full test suite**

Run (from `DocuProj/`): `.\.venv\Scripts\pytest -v`
Expected: PASS — Plan 1 (16) + Plan 2 (7) + Plan 3 (9) = 32 tests.

- [ ] **Step 5: Commit**

```bash
git add DocuProj/engine/parsers/__init__.py DocuProj/engine/__init__.py DocuProj/tests/test_parser_python.py DocuProj/tests/test_parser_ts.py
git commit -m "feat(parsers): add parse() dispatcher and public exports"
```

---

## Self-Review

**Spec coverage (Parsers, §3, validated §12):**
- tree-sitter per language, traversal extractors — Tasks 1,3,4,5 ✓
- Inbound routes (method, path, handler location) for FastAPI per-feature routers + prefix — Task 3 ✓
- Outbound HTTP calls (Angular `this.http.<verb>`) — Task 5 ✓
- `endPointConfig` URL map (deterministic facts feeding Linker resolution) — Task 4 ✓
- `parse(repoPath, language) -> RepoFacts` interface — Task 6 ✓
- Deferred (correctly): variable→config→URL resolution and cross-repo join → Linker (Plan 4); function defs / imports / intra-repo calls beyond the first hop (YAGNI); other languages (Java/C#) until a target flow needs them.

**Placeholder scan:** No TBD/TODO; all code complete; every run step has command + expected outcome. tree-sitter node fields (`assignment.left/right`, `call.function/arguments`, `attribute.object/attribute`, `member_expression.object/property`, `pair.key/value`, `decorated_definition.definition`) were verified live against tree-sitter 0.25 before writing.

**Type consistency:** `extract_fastapi_routes(repo_path, repo)`, `extract_angular_outbound(repo_path, repo) -> (outbound, configs)`, `parse(repo_path, language, repo)`, and `RepoFacts{repo, language, endpoints, outbound_calls, config_urls}` are referenced identically across tasks/tests. `_VERBS` is the same set in both extractors.
