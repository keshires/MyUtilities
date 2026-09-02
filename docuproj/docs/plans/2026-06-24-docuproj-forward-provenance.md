# DocuProj Forward Data-Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (slice by slice). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Trace an endpoint *forward* to where its data comes from — `UI → edfx-api → Tessera → Postgres` — instead of only linking who-calls-whom by HTTP path. Realizes the spec §1 vision ("the complete flow… into every downstream repository it touches").

**Why it's missing today:** the linker builds flows *backward* (sources → endpoint). It doesn't model what happens *inside* a handler: the outbound service calls and DB queries that produce the data. This plan adds the forward layer.

## Architecture (the new layer)

```
Endpoint (route) ──handler body──▶ outbound calls ──resolve──▶ downstream Endpoint ──▶ (recurse)
                  └──────────────▶ DB accesses ─────────────▶ Datastore (terminal)
```

Three new pieces on top of the existing parse→link→model:
1. **DB extraction** — per repo, find persistence access (SQLAlchemy `.query/.execute`, raw SQL, psycopg) → `DbAccess` facts.
2. **Handler-scoped association** — attach each repo's outbound calls + DB accesses to the *enclosing route handler*, following a light intra-repo call graph (handler → helper → client/db call) by function name.
3. **Forward flow tracer** — from a chosen endpoint, walk handler → (DB → datastore node) and (outbound → resolved downstream endpoint → recurse), producing a deep `Flow` that terminates at datastores.

## Data-model additions

```python
# engine/facts.py
class DbAccess(BaseModel):
    engine: str        # "sqlalchemy" | "raw_sql" | "psycopg"
    detail: str        # table name or query fragment (best-effort)
    code_ref: CodeRef

# RepoFacts gains: db_accesses: list[DbAccess] = []
#                  handler_provenance: dict[endpoint_id, {"outbound":[idx], "db":[idx]}]  (Slice 2)

# engine/models.py — extend the enums:
#   FlowNode.kind  += "datastore"
#   FlowEdge.kind  += "db"
```

## Scope & honesty
- **Languages:** Python (full) + Angular (UI). `.NET` (`edfx-bond-api`) and Node/Puppeteer (`edfx-render-pdf-reports`) have no/partial extractors — flows through them stop at the boundary. Documented in `REPOS.md`.
- **Call graph is name-based** (handler → callee by bare name) — a deterministic approximation; method/import indirection is best-effort, ambiguous hops fall to the Claude resolver.
- **Requires cloning the chain repos** (e.g. `edfx-tessera-service`) — Slice 4.

---

## Slice 1 — Python DB-access extractor  *(execute now)*

**Files:** `engine/parsers/python_db.py` (new), `engine/facts.py` (+`DbAccess`, `RepoFacts.db_accesses`), `engine/parsers/__init__.py` (parse() returns db), `tests/fixtures/py_db/repo.py`, `tests/test_parser_python_db.py`.

Detects three patterns and records `DbAccess(engine, detail, code_ref)`:
- `<x>.query(Model)` / `<x>.execute(stmt)` → engine `sqlalchemy`, detail = first-arg text.
- string literals containing `SELECT … FROM <t>` / `INSERT INTO <t>` → engine `raw_sql`, detail = table.
- `psycopg`/`asyncpg` `.execute(...)` → engine `psycopg`.

- [ ] **Step 1:** Add `DbAccess` to `facts.py` and `db_accesses: list[DbAccess] = []` to `RepoFacts`.
- [ ] **Step 2:** Fixture `tests/fixtures/py_db/repo.py` with a `session.query(Portfolio)`, a raw `"SELECT id FROM portfolios"`, and a non-DB line.
- [ ] **Step 3:** Failing test `test_parser_python_db.py`: `extract_python_db(_FIX, repo="edfx-api")` returns ≥2 accesses; one `sqlalchemy` with detail `Portfolio`; one `raw_sql` whose detail mentions `portfolios`.
- [ ] **Step 4:** Implement `engine/parsers/python_db.py::extract_python_db(repo_path, repo, consts=None)` (tree-sitter walk; reuse `_support`/`resolve_expr`; regex for SQL tables).
- [ ] **Step 5:** Wire into `parse()` python branch: `db_accesses=extract_python_db(repo_path, repo, consts)`.
- [ ] **Step 6:** Full suite green; commit `feat(parsers): Python DB-access extractor`.

---

## Slice 2 — Handler-scoped facts + intra-repo call graph  *(plan, execute next)*

- Build per-repo `FuncFacts{name -> {callees:set, outbound:[idx], db:[idx]}}` by walking each `function_definition` and collecting call-expression callee names, outbound matches, and DB matches within its body.
- For each endpoint, resolve the handler function (name known from the route), BFS reachable callees, union their outbound + DB → `handler_provenance[endpoint_id]`.
- Tests: a fixture where a route handler calls a helper that does the DB/outbound; assert the endpoint's provenance includes them.

## Slice 3 — Forward flow tracer  *(plan)*

- `trace(model, facts, resolver=None, max_depth=4) -> AnalysisModel`: for each endpoint, build a forward `Flow`: route node → for each handler-reachable DB access add a `datastore` node + `db` edge; for each handler-reachable outbound call resolve to a downstream endpoint (deterministic path match, else Claude) and recurse into that endpoint's handler (depth-limited, cycle-guarded).
- Extend `FlowNode.kind` with `datastore`, `FlowEdge.kind` with `db`.
- Tests: synthetic 3-repo chain (ui→gw→svc→db) yields a 4-node deep flow terminating at a datastore.

## Slice 4 — Ingest chain repos + dashboard DB lane  *(plan)*

- Expand `projects/edfx-flow.json` (or a new `edfx-full.json`) to include `edfx-tessera-service` (+ others on the portfolio path); clone them into `.workspace`.
- Dashboard: render `datastore` nodes (distinct lane/style, e.g. cylinder), `db` edges; deep multi-lane chains already supported by the swimlane layout.

## Slice 5 — Real-repo validation  *(plan)*

- Analyze the portfolio chain across cloned repos; confirm a flow renders `UI → edfx-api → edfx-tessera-service → Postgres`. Report depth + any boundaries hit (.NET, unresolved hops).

---

## Self-Review (slice 1)
- `DbAccess` + extractor are self-contained and offline-testable — no dependency on the harder call-graph/tracer slices.
- New node/edge kinds are added when first used (Slice 3), not now, to avoid unused-enum churn.
- Honest boundaries (`.NET`, name-based call graph, repos-to-clone) are documented up front in REPOS.md and this plan.
