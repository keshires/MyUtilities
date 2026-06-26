# DocuProj

A static analyzer that builds **cross-repo flows** across the EDFX service fleet: who calls an
API endpoint (UI → gateway → service) and — forward — **where it gets its data** (downstream
services + the database). Answers "what does this endpoint touch?" without reading every repo by
hand, and renders it as an interactive swimlane dashboard.

```
project.json ─▶ Ingest ─▶ Parse ─▶ Link ─▶ Cache ─▶ API ─▶ Dashboard
                                     │                       (swimlanes + step popups)
                                     └─ forward trace ─▶ downstream services ─▶ datastore
```

## Quickstart

```bash
cd DocuProj
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt          # Linux/macOS: .venv/bin/pip

# clone the repos on the path you care about (edfx-api is branch `master`, others `main` — see REPOS.md)
WS=.workspace/edfx-flow
git clone --depth 1 --branch main   https://github.com/moodysanalytics/edfx-app-ui          $WS/edfx-app-ui
git clone --depth 1 --branch master https://github.com/moodysanalytics/edfx-api             $WS/edfx-api
git clone --depth 1 --branch main   https://github.com/moodysanalytics/edfx-tessera-service $WS/edfx-tessera-service
```

### One command — trace where an endpoint gets its data
```bash
./.venv/Scripts/python flow.py portfolios        # any endpoint substring (leading / is fine)
./.venv/Scripts/python flow.py bulk --claude      # also resolve variable-URL service hops (needs ANTHROPIC_API_KEY)
```
Prints the provenance chain per matching endpoint — node `kind` / `repo` / `label` and the exact
`file:line`, plus edges (`db` = reads DB, `http` = calls a service).

### Visual dashboard
```bash
./.venv/Scripts/python -m uvicorn serve_demo:app --host 127.0.0.1 --port 8011
# open http://127.0.0.1:8011/app/  — filter endpoints, click one for its swimlane, click a node for its code ref
```

## For teammates (Claude Code skill)
`.claude/skills/troubleshooting-edfx-flows/` — ask Claude *"where does `/edfx/v2/portfolios/list` get
its data?"* or *"what calls this route?"* and it drives DocuProj for you.

## Engine API
| Function | Returns | Direction |
|----------|---------|-----------|
| `parse(repo_path, language, repo=)` | `RepoFacts` (routes, outbound calls, DB, config, handler provenance) | — |
| `link(facts, project)` | `AnalysisModel` | backward: who calls each endpoint |
| `trace_flows(facts, project, resolver=)` | `AnalysisModel` | forward: endpoint → downstream → datastore |
| `ClaudeResolver()` | resolver | resolves runtime-variable service URLs (needs `ANTHROPIC_API_KEY`) |
| `create_app(projects_dir, workspace, store=)` | FastAPI app | the dashboard |

**Languages:** Python (FastAPI routes, outbound HTTP, DB) and Angular/TypeScript (HTTP client +
`endPointConfig`). `.NET` and Node have no/partial extractors — flows stop at those repos.

## How linking works (deterministic + Claude)
1. **Deterministic** — match a UI config URL / outbound-call path against route paths (with
   constant, f-string, and `include_router`-prefix resolution); follow handler call graphs to DB.
2. **Claude resolver (optional)** — the runtime-variable hops deterministic matching can't resolve
   (`tessera_client.get(url)`) are batch-resolved by `claude-opus-4-8`, lighting up the full
   `UI → gateway → service → Postgres` chain. Behind the `Resolver` seam; tests run offline with a mock.

## Layout
```
engine/        parsers/ (python_fastapi, python_http, python_db, python_handlers, ts_angular, _router_graph, _consts),
               models, facts, ingest, linker, claude_resolver, analyze, cache, api
dashboard/     no-build HTML/CSS/JS swimlane UI (served by FastAPI)
projects/      sample project.json inputs (edfx-flow.json)
tests/         74 tests (offline; real repos validated separately)
docs/          design spec + docs/plans/ (how each capability was built)
REPOS.md       the 21-repo EDFX fleet, languages, default branches
flow.py        one-command tracer    serve_demo.py / claude_demo.py   demo entrypoints
```

## Status
74 tests passing (`./.venv/Scripts/pytest`). Built across 12 plans / 8 stages — data model →
ingest → parse → link → API → dashboard → cross-repo depth → constant/include-router/import
resolution → swimlane UI → Claude resolver → forward data-provenance. Deterministic engine links
UI → service → DB; variable-URL service-to-service edges resolve with the Claude key.
