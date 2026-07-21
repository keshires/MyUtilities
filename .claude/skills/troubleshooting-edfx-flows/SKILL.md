---
name: troubleshooting-edfx-flows
description: Use when troubleshooting how EDFX services connect - which repos/database an endpoint touches, where an API gets its data, what calls a given route, or visualizing a cross-repo request flow (e.g. "/edfx/v2/portfolios/list -> Tessera -> Postgres"). Drives the DocuProj analyzer in this repo.
---

# Troubleshooting EDFX Flows (DocuProj)

The analyzer lives in the **`DocuProj/`** subfolder of this repo. All of its commands
must run from there (so the `engine` package imports). This skill is the short path;
the full recipes, engine API, and common mistakes are in the canonical skill at
**`DocuProj/.claude/skills/troubleshooting-edfx-flows/SKILL.md`** — read it for depth.

## Setup (once)

```bash
cd DocuProj
python bootstrap.py        # creates .venv, installs deps, clones the default repo chain
```

Cloned repos live in the gitignored `.workspace/edfx-flow/`. **`edfx-api` is branch
`master`; most others are `main`** — full fleet + branches in `DocuProj/REPOS.md`.
Add a repo on your path: `python bootstrap.py --repos edfx_entity_api` (or clone it
manually into `.workspace/edfx-flow/`).

## The one command

From `DocuProj/`, trace where any endpoint gets its data (substring match):

```bash
./.venv/Scripts/python flow.py portfolios          # leading / is fine; e.g. /edfx/v2/portfolios/list
./.venv/Scripts/python flow.py portfolios --claude  # also resolve variable-URL service hops (needs ANTHROPIC_API_KEY)
```

Output is the provenance chain per matching endpoint — node `kind` / `repo` / `label`
and the exact `file:line`, plus edges (`db` = reads DB, `http` = calls a service).

## Visual dashboard

```bash
cd DocuProj
./.venv/Scripts/python -m uvicorn serve_demo:app --host 127.0.0.1 --port 8011
# open http://127.0.0.1:8011/app/  — filter endpoints, click one for its swimlane
```

## Domain reference — entity categorization
Definitions and business rules for entity kinds (Public / Private / Custom /
Public+Private Customized), the `data_type` / `custom_id` / `financials_type`
combinations, what a NULL `financials_process_id`/`_status` means, and the
customized-entity detection SQL: **`references/entity-categorization.md`**. Read it
before writing any query that filters entities by kind or financials status.

## When the chain stops short
- **Repo not cloned** — a service not in `.workspace` is invisible; clone it (right branch).
- **Variable-URL hop missing** — gateway->service calls like `tessera_client.get(url)` only
  link with `--claude` + `ANTHROPIC_API_KEY`.
- **Unsupported language** — `edfx-bond-api` (.NET), `edfx-render-pdf-reports` (Node) have
  no/partial extractors; flows stop there. See `DocuProj/REPOS.md`.

For backward ("what calls this route?") and scripting recipes, open the canonical skill
in `DocuProj/.claude/skills/troubleshooting-edfx-flows/`.