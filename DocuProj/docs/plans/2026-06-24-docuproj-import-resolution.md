# DocuProj Import Resolution (router include graph) Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Checkbox steps.

**Goal:** Resolve cross-file router references (`api.router`, `module.router`, imported router vars) and build the `include_router` graph so a route's full prefix accumulates from the app mount down. Closes the `edfx_entity_api` gap (its `/entity` mount flows through a cross-file `api.router` aggregator).

**Architecture:** `engine/parsers/_router_graph.py` builds, repo-wide: (1) router definitions `(file, var) -> own prefix`; (2) per-file import maps (`from PKG import NAME [as A]`, `import A.B as D`) mapping a name to a module path / origin module; (3) `include_router` edges with each ref resolved to a router node (or ROOT for `app.*`); (4) `full_prefix(node)` accumulated from ROOT via `full(child) = full(parent) + includePrefix + own(child)`, default = own prefix when unmounted. The FastAPI extractor uses `full_prefix[(file,var)]` instead of the per-file prefix.

**Module→file:** dotted path → `<repo>/<parts>.py` or `<repo>/<parts>/__init__.py`.

**Tech Stack:** tree-sitter (existing), pytest. Multi-file synthetic fixture + 4-repo re-validation.

---

### Task 1: multi-file fixture + failing test
Fixture `tests/fixtures/py_include_graph/app/…` mirroring both real styles:
- `server.py`: `from app.routers import api`; `from app.routers.loans import loan_router`; `CTX='entity'`; `app.include_router(api.router, prefix=f'/{CTX}')`; `app.include_router(loan_router, prefix="/loans")`.
- `routers/api.py`: `from app.routers.v1 import items_route`; `router=APIRouter()`; `router.include_router(items_route.router)`.
- `routers/v1/items_route.py`: `PFX="/v1"`; `router=APIRouter()`; `@router.get(path=PFX + "/items")`.
- `routers/loans.py`: `loan_router=APIRouter()`; `@loan_router.get(path="/x")`.
Failing test: `extract_fastapi_routes(fixture)` paths ⊇ `{"/entity/v1/items", "/loans/x"}`.

### Task 2: `_router_graph.py`
- [ ] `build_full_prefixes(repo_root, consts) -> dict[(file_rel,var), str]`: parse imports, resolve refs, build edges, accumulate from ROOT (parent unresolved/`app` → ROOT; default = own prefix).

### Task 3: integrate
- [ ] FastAPI extractor builds `full_prefixes` once; per file, `prefixes = {var: full_prefixes[(rel,var)]}`; drop the old per-file/include-prefix path. Keep `path=` kwarg + const/f-string resolution.

### Task 4: full suite + 4-repo validation
- [ ] `pytest -q` all pass; analyze 4 repos → entity_api routes now `/entity/v1/...` and **link to the UI** (`entitySearchApiUrl`); edfx-api/financials unchanged or better; report flow delta.

## Self-Review
- Cross-file `module.router` + imported router-var refs resolved; ROOT auto-detected (unresolved parent).
- Safety: default full_prefix = own prefix → unmounted/unresolved routers behave as today (no regression).
- Honest limit: unresolved modules (e.g. non-repo packages) fall back to own prefix.
