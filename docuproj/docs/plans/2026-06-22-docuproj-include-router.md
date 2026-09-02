# DocuProj include_router + path= + f-string Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Checkbox (`- [ ]`) steps.

**Goal:** Fix FastAPI route extraction for repos that (a) pass the path as a `path=` keyword arg, (b) build paths/prefixes from f-strings, and (c) apply prefixes via `<obj>.include_router(<routerVar>, prefix=…)`. Targets `edfx_entity_api` (path= kwarg) and `edfx-api` (per-router mount prefixes).

**Architecture:** `resolve_expr` gains f-string support (concat `string_content` + resolved `interpolation` expressions). `_decorator_route` reads the `path=` keyword arg when there's no positional path. A repo-wide `build_include_prefixes()` maps `routerVar -> resolved mount prefix` from `include_router(IDENT, prefix=…)` calls; effective router prefix = mount prefix + the router's own `APIRouter(prefix=…)`.

**Known non-goal:** aggregator routers referenced by attribute (`api.router`) across files (entity_api's `/entity` top mount) — needs import resolution, out of scope. Documented.

**Tech Stack:** tree-sitter (existing), pytest. Synthetic fixtures + 4-repo re-validation.

---

### Task 1: f-string resolution in `resolve_expr`

**Files:** Modify `engine/parsers/_consts.py`; Test `tests/test_consts.py` (append).

- [ ] Failing test: `resolve_expr` of an f-string node `f'/{CTX}/x'` with `consts={"CTX":"entity"}` → `"/entity/x"`; unresolved interpolation → `None`.
- [ ] Implement: in the `string` branch, if the node has `interpolation` children, concatenate `string_content` text with `resolve_expr` of each interpolation's inner expression; any `None` → `None`.
- [ ] Run test → pass. Commit `feat(parsers): resolve f-strings in resolve_expr`.

### Task 2: `path=` kwarg + per-router `include_router` prefixes

**Files:** Modify `engine/parsers/python_fastapi.py`; Create fixture `tests/fixtures/py_fastapi_include/svc.py`; Test `tests/test_parser_python.py` (append).

- [ ] Fixture: a router whose route uses `@r.get(path=PFX + "/items")` and is mounted via `app.include_router(r, prefix="/svc")` in the same file → expected path `/svc/v1/items` (PFX="/v1").
- [ ] Failing test: `extract_fastapi_routes(fixture)` contains `/svc/v1/items`.
- [ ] Implement:
  - `build_include_prefixes(repo_root, consts)`: scan all `*.include_router(IDENT, prefix=P)` calls; `map[IDENT] = resolve_expr(P)` (skip non-identifier router refs like `api.router`).
  - `_decorator_route`: if the first positional arg doesn't resolve, look for a `keyword_argument` named `path` and resolve its value.
  - `_router_prefixes(root, consts, include_prefixes)`: effective prefix = `include_prefixes.get(var,"") + own_prefix`.
  - `extract_fastapi_routes`: build `include_prefixes` repo-wide (once) and thread through.
- [ ] Run `tests/test_parser_python.py` → pass (existing + new). Commit `feat(parsers): handle path= kwarg and per-router include_router prefixes`.

### Task 3: full suite + 4-repo re-validation

- [ ] `.\.venv\Scripts\pytest -q` → all pass.
- [ ] Analyze the 4 repos; report: entity_api routes now resolve to real decorator paths (e.g. `/v1/customEntity`) instead of `/`; edfx-api `loan_v2` routes now carry `/edfx/v2/entities`; note entity_api `/entity` top prefix still absent (aggregator/import limitation) so UI→entity links remain gated on that.

## Self-Review
- path= kwarg, f-strings, per-router include prefixes covered (Tasks 1–2).
- edfx-api safety: per-router association (not global) — non-mounted routers unchanged.
- Honest residual: entity_api attribute-aggregator `/entity` prefix needs import resolution (logged).
