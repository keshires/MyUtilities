# Day2Day Utilities — Skills + Catalog Dashboard

**Date:** 2026-07-07
**Status:** Approved

## Goal

Make the production tools in `Day2Day_Utillites/` discoverable and self-documenting
by (a) capturing them as **Claude Code skills** (task-oriented runbooks) and (b)
surfacing them in a read-only **catalog dashboard** with run history. Both are driven
by a single hand-authored manifest so utility facts live in exactly one place.

This mirrors the pattern already proven in this repo by **DocuProj** (a `SKILL.md`
plus a FastAPI dashboard served at `/app/`).

## Scope

### In scope — the 10 production utilities

> Updated 2026-07-13: originally scoped at 9. During implementation a 10th
> utility, `test_single_entity_refresh.py` (single-entity refresh verifier),
> was folded into the `stale-entity-refresh` family — see the plan handoff note.
> The manifest and dashboard therefore expose 10 utilities.

| Script | Category |
|--------|----------|
| `refresh_stale_non_public_entities.py` | stale-entity-refresh |
| `validate_stale_entities.py` | stale-entity-refresh |
| `export_stale_entities_from_excel.py` | stale-entity-refresh |
| `test_single_entity_refresh.py` | stale-entity-refresh |
| `run_portfolio_kpis_postgres.py` | portfolio-kpi-ops |
| `portfolio_kpi_metrics_postgres.py` | portfolio-kpi-ops |
| `financials_delete_custom_entity.py` | edfx-entity-ops |
| `EDFX_ProcessStatus.py` | edfx-entity-ops |
| `build_opensearch_entity_query_from_csv.py` | edfx-entity-ops |
| `DynamoDB_BatchUpdate_CreatedBy.py` | dynamo-batch-update |

### Out of scope — archived, not cataloged

Seven throwaway load-test / Spark POC scripts move to `Day2Day_Utillites/archive/`:
`Sample2Test.py`, `SampleTest.py`, `Sample_RCTest.py`, `LDGLoadTest.py`,
`pysparkpoc.py`, `pyspakrPeedata.py`, `PeerMetricFile.py`.
Verified (grep) that no kept script imports any of them.

`project_paths.py` (shared infra, imported by 8 scripts) and the empty
`SecurityService.py` stub stay in place and are not cataloged. `SecurityService.py`
is left as-is (not archived) because it is a placeholder other work may fill.

### Explicitly not doing (YAGNI)

- No execution-from-UI (no "Run" button). Dashboard is read-only.
- No `argparse` introspection. The manifest is hand-authored.
- No changes to the 9 production scripts themselves.
- No test framework introduced (repo has none today).

## Architecture

```
Day2Day_Utillites/
  utilities.yaml            NEW  single source of truth (hand-authored)
  dashboard/                NEW  FastAPI app (mirrors DocuProj/serve_demo)
    serve.py                     API + static mount
    app/index.html               static SPA (vanilla JS, no build step)
  archive/                  NEW  7 POC/test scripts + README.md
    README.md
  <9 production scripts>         unchanged
.claude/skills/             NEW  4 SKILL.md runbooks
  stale-entity-refresh/SKILL.md
  portfolio-kpi-ops/SKILL.md
  edfx-entity-ops/SKILL.md
  dynamo-batch-update/SKILL.md
```

The manifest is the hub: the dashboard reads it at request time; the skills cite it
as the canonical argument/env reference instead of duplicating arg tables.

## Component 1 — Manifest (`utilities.yaml`)

One entry per production utility. Schema (validated by a pydantic model on load):

```yaml
utilities:
  - id: refresh-stale-non-public-entities   # kebab-case, stable, used in API paths
    name: Refresh Stale Non-Public Entities
    script: refresh_stale_non_public_entities.py
    category: stale-entity-refresh          # one of the 4 family ids
    purpose: "Refresh stale private/custom entities via Tessera refreshEntities API."
    invocation: cli                          # cli | env-config
    args:                                    # omit/empty for env-config scripts
      - flag: --entity-type
        choices: [custom, private]
        default: private
        help: "Which entity family to refresh."
      - flag: --dry-run
        type: bool
        help: "Query and batch but do not submit."
      # ...remaining args...
    env_required: [MOODYS_SSO_USERNAME, MOODYS_SSO_PASSWORD, TESSERA_BASE_URL,
                   TESSERA_POSTGRES_HOST, TESSERA_POSTGRES_DB, TESSERA_POSTGRES_USER,
                   TESSERA_POSTGRES_PASSWORD]
    outputs:
      logs_glob: "refresh_stale_entities_*"  # matched under Day2Day_Utillites/logs/
      output_glob: "stale_entities/*"        # matched under Day2Day_Utillites/output/
      summary_suffix: ".summary.json"        # optional; run-summary sidecar
    docs:
      - "docs/superpowers/specs/2026-07-02-selectable-staleness-date-column-design.md"
    safety: "Hits prod Postgres + Tessera API. Run --dry-run first."
```

Field notes:
- `invocation: env-config` marks scripts driven entirely by `.env` (no argparse):
  `EDFX_ProcessStatus.py`, `DynamoDB_BatchUpdate_CreatedBy.py`. Their `args` list is
  empty; the dashboard shows the env vars as the configuration surface instead.
- `args[].type: bool` renders as a checkbox in the arg form; otherwise a text input.
- `outputs.*_glob` are relative to the standard `project_paths` `logs/` and `output/`
  directories. Any field may be omitted when a utility does not produce that artifact.

A malformed or missing manifest yields a clear HTTP 500 with the validation error, not
a stack trace to the UI.

## Component 2 — Dashboard (`Day2Day_Utillites/dashboard/`)

Stack: **FastAPI + uvicorn**, static single-page `app/index.html` with vanilla JS.
No build step. Matches DocuProj's `serve_demo` conventions.

### API (`serve.py`)

| Route | Returns |
|-------|---------|
| `GET /api/utilities` | Parsed manifest, grouped by category. |
| `GET /api/utilities/{id}/runs` | Recent runs for that utility: scans `logs/` for `logs_glob` and `output/` for `output_glob`; each run = `{name, mtime, size, summary?}` where `summary` is the parsed `.summary.json` when present. Newest first. Unknown `id` → 404. |
| `GET /app/` (+ static) | The SPA. |
| `GET /download/{kind}/{name}` | Serve a single log/output artifact for inspection; path-traversal guarded (name resolved against the known dir, must stay inside it). |

Run-history scanning tolerates missing dirs and malformed/partial JSON summaries
(skip the summary, still list the file). Never crashes on bad data.

Launch (documented in each skill and the README):
```powershell
cd Day2Day_Utillites
.\.venv\Scripts\python -m uvicorn dashboard.serve:app --host 127.0.0.1 --port 8021
# open http://127.0.0.1:8021/app/
```

### UI (single page, read-only)

- **Left column:** utilities grouped under the 4 family headings; each is a card
  showing name, purpose, an `cli` / `env-config` badge, and required-env chips.
- **Right detail panel** (on card click):
  - **Arg form** — one input per `args` entry (checkbox for `bool`, text otherwise),
    that live-builds a copy-ready command string
    (`python <script> --flag value ...`) with a copy button.
  - **Environment** — the `env_required` list.
  - **Outputs** — the log/output locations.
  - **Docs** — links to any `docs` entries.
  - **Run History** — table from `/api/utilities/{id}/runs`: filename, timestamp,
    key summary metrics when a `.summary.json` exists, and artifact download links.

## Component 3 — Skills (4 × `SKILL.md`)

Location: repo-root `.claude/skills/<name>/SKILL.md`, matching the existing
`troubleshooting-edfx-flows` skill. Each has YAML frontmatter (`name`, and a
`description` beginning "Use when …" so it is discoverable) and a body covering:

1. When to use / when not to.
2. Prereqs: `.venv` active, required `.env` keys (named, pointing at the manifest for
   the authoritative list).
3. The exact command(s) per step, in order.
4. Safety notes: dry-run first, prod Postgres / prod API warnings where relevant.
5. Where outputs land (`logs/`, `output/`, summary JSON).
6. A pointer to launch the dashboard for browsing/args/run-history.

Skills cite `utilities.yaml` as the canonical arg reference rather than duplicating
full arg tables (avoids drift).

| Skill | Wraps | Shape |
|-------|-------|-------|
| `stale-entity-refresh` | export → validate → refresh (3 scripts) | 3-step pipeline runbook |
| `portfolio-kpi-ops` | run KPIs + KPI-log analytics (2 scripts) | Two related tasks |
| `edfx-entity-ops` | delete entity / process-status / build OpenSearch query (3) | Three EDFX tasks |
| `dynamo-batch-update` | dry-run-guarded Dynamo field migration (1) | Single guarded migration |

## Component 4 — Archive + docs

- Move the 7 POC scripts to `Day2Day_Utillites/archive/`; add `archive/README.md`
  stating they are unmaintained load-tests / Spark experiments kept for reference.
- Update repo `README.md` and add a `Day2Day_Utillites/Docs/` note pointing at the
  dashboard launch command and the 4 skills.

## Error handling

- **Manifest:** validated on load; malformed → HTTP 500 with the validation message.
- **Run scan:** missing dirs / bad JSON summaries are skipped, not fatal.
- **Downloads:** path-traversal guarded; requests resolving outside the known dir → 404.
- **Archive move:** pre-verified no kept script imports a moved one (grep, done).

## Verification

No automated test suite exists in this repo; verification is manual and mirrors how
the existing scripts are validated:

1. Dashboard starts; `GET /api/utilities` returns all 10 utilities under the correct
   4 families.
2. UI renders the 10 cards; clicking one builds a correct command string in the arg form.
3. **Run History** populates for `stale-entity-refresh` and `portfolio-kpi-ops`
   (both already have files under `logs/` and `output/`).
4. Each skill's copy-run commands match the manifest and the script's real args.
5. Smoke-check: `python -c "import <module>"` on the 9 kept scripts after the archive
   move confirms no import broke.

## Decisions

- **Hand-authored manifest** over argparse introspection — 3 scripts have no argparse,
  and the tools change rarely; explicit beats fragile.
- **Read-only dashboard** — these tools touch prod Postgres / Tessera / DynamoDB;
  execution-from-UI is deferred (would need dry-run gating + confirmation).
- **4 thematic skills, not 19 per-script wrappers** — operators think in tasks.
- **Archive (not delete) the POCs** — declutters the catalog, preserves reference.