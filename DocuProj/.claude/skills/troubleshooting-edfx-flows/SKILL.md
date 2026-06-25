---
name: troubleshooting-edfx-flows
description: Use when troubleshooting how EDFX services connect - which repos/database an endpoint touches, where an API gets its data, what calls a given route, or visualizing a cross-repo request flow (e.g. "/edfx/v2/portfolios/list -> Tessera -> Postgres"). Drives the DocuProj analyzer in this repo.
---

# Troubleshooting EDFX Flows (DocuProj)

## Overview

DocuProj statically analyzes the EDFX repos and builds **cross-repo flows**: who calls an
endpoint (UI/config), and — forward — where it gets its data (downstream services + database).
Use it to answer "what does this endpoint touch?" without reading every repo by hand.

All commands run from the **`DocuProj/`** directory. Cloned repos live in the gitignored
`.workspace/edfx-flow/`. The full fleet + each repo's default branch are in **`REPOS.md`**.

## One-time setup

```bash
cd DocuProj
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt   # Windows; Linux/macOS: .venv/bin/pip
```

## Step 1 — clone the repos on the path you're troubleshooting

A repo is invisible until it's cloned into `.workspace`. **`edfx-api` is branch `master`; most
others are `main`** (check `REPOS.md`). Example for a UI→gateway→Tessera→DB question:

```bash
WS=.workspace/edfx-flow
git clone --depth 1 --branch main   https://github.com/moodysanalytics/edfx-app-ui          $WS/edfx-app-ui
git clone --depth 1 --branch master https://github.com/moodysanalytics/edfx-api             $WS/edfx-api
git clone --depth 1 --branch main   https://github.com/moodysanalytics/edfx-tessera-service $WS/edfx-tessera-service
```

## Step 2 — pick the recipe for the question

| Question | Function | Direction |
|----------|----------|-----------|
| "Where does endpoint X get its data?" (services + DB) | `trace_flows` | forward: route → downstream → datastore |
| "What calls / consumes endpoint X?" | `link` | backward: UI/config → route |
| "Resolve the fuzzy hops too" (variable-URL service calls) | `trace_flows(..., resolver=ClaudeResolver())` | needs `ANTHROPIC_API_KEY` |
| "Let me click around visually" | the dashboard (below) | both |

**Trace where an endpoint's data comes from.** Run this **from the `DocuProj/` directory**
(save as a `.py` file there or pipe via stdin) so the `engine` package imports — running it
from `/tmp` or elsewhere fails with `ModuleNotFoundError: engine`. Use `./.venv/Scripts/python`:

```python
from engine import parse, trace_flows, Project, RepoRef
WS = ".workspace/edfx-flow"
specs = [("edfx-app-ui", "angular", "main"),
         ("edfx-api", "python", "master"),
         ("edfx-tessera-service", "python", "main")]
facts = [parse(f"{WS}/{f}", lang, repo=f) for f, lang, _ in specs]
project = Project(id="edfx", name="EDFX",
                  repos=[RepoRef(url="x", folder=f, branch=b, sha=f) for f, _, b in specs])
model = trace_flows(facts, project)            # add resolver=ClaudeResolver() for variable-URL hops
for fl in model.flows:
    if "portfolios" in fl.endpoint_id:         # filter to the endpoint you care about
        for n in fl.nodes:
            print(f"{n.kind:9} {n.repo:24} {n.label[:34]:34} {n.code_ref.file}:{n.code_ref.line}")
```

Node kinds: `ui` (caller), `route` (endpoint), `outbound` (service call), `datastore` (DB).
Edge kinds: `http` (service call), `db` (DB read). `code_ref` is the exact file:line to open.

## The visual dashboard (best for exploring)

```bash
./.venv/Scripts/python -m uvicorn serve_demo:app --host 127.0.0.1 --port 8011
# open http://127.0.0.1:8011/app/  -> filter endpoints, click one, click a node for its code ref
```

`serve_demo.py` lists which repos it analyzes — edit `SPECS` there to add the repos for your path.

## Engine quick reference

- `parse(repo_path, language, repo=name)` → `RepoFacts`. `language`: `"python"` or `"angular"`.
- `link(facts, project)` → backward `AnalysisModel` (who calls each endpoint).
- `trace_flows(facts, project, resolver=None)` → forward `AnalysisModel` (endpoint → downstream → DB).
- `ClaudeResolver()` → resolves runtime-variable service URLs (set `ANTHROPIC_API_KEY` first).
- `create_app(projects_dir, workspace, store={...})` → the FastAPI dashboard app.

## Common mistakes

- **Wrong branch:** `edfx-api` is `master`, not `main` — clone fails or analyzes the wrong tree.
- **Repo not cloned:** a service not in `.workspace` is invisible; the chain stops at the boundary.
- **Variable-URL hops missing:** gateway→service calls like `tessera_client.get(url)` only link with
  `ClaudeResolver()` + `ANTHROPIC_API_KEY` — deterministic matching can't resolve a runtime variable.
- **Unsupported language:** `edfx-bond-api` is .NET and `edfx-render-pdf-reports` is Node — no/partial
  extractor, so flows stop at those repos (see `REPOS.md`).

## Reference
- `REPOS.md` — the 21-repo fleet, languages, and default branches.
- `docs/2026-06-09-docuproj-design.md` — design spec; `docs/plans/` — how each capability was built.