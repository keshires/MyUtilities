# DocuProj — Phase 1 Delivery Summary

**Status:** Complete — all work merged to `main`
**Date:** 2026-06-21
**Scope:** Plans 1–6 (the Phase-1 MVP vertical)

---

## Outcome

A working end-to-end tool that ingests a list of repositories, analyzes how they
connect, and lets an engineer **pick an API endpoint and see its complete cross-repo
flow** in a browser — with clickable code references at each step. Proven against the
live EDFX service fleet.

**Pipeline delivered:** `project.json → Ingest → Parse → Link → Cache → API → Dashboard`

**Quality:** 54 automated tests passing; every subsystem validated against the real
EDFX repos.

---

## Plan 1 — Engine Foundation (data model + cache)

- Defined the **stable data contract** (pydantic v2): `Project`, `RepoRef`, `Endpoint`,
  `FlowNode`, `FlowEdge`, `Flow`, `CodeRef`, `AnalysisModel`.
- Enforced **validation**: link confidence bounded 0.0–1.0; node/edge `kind` restricted
  to valid enums.
- **camelCase JSON contract** for all models (so the dashboard and API speak one shape).
- **Content-addressed cache** keyed by `(analyzer version + repo commit SHAs)` — re-serves
  results with zero re-work when nothing changed.
- Project scaffolding: Python package, dependency management, test harness.

## Plan 2 — Ingestor (get the source, always latest)

- **`project.json` loader** mapping the input file to the internal model.
- **Git automation**: clone if absent, else fetch + reset to the latest of the selected branch.
- **Per-repo branch selection** with override support.
- Records the **resolved HEAD commit SHA** per repo (feeds the cache key).
- Workspace layout under a gitignored `.workspace/`.
- Canonical **sample input** for the 6-repo EDFX fleet.

## Plan 3 — Parsers (extract structural facts)

- **tree-sitter** integration for Python and TypeScript (deterministic, no LLM).
- **FastAPI route extractor**: discovers `APIRouter(prefix=…)` declarations and
  `@router.<verb>("path")` decorators → inbound endpoints with method, full path, and
  handler location.
- **Angular `endPointConfig` extractor**: pulls the UI's service base-URL map.
- **Angular outbound-call extractor**: finds `this.http.<verb>(…)` call sites.
- Unified **`parse(repo, language)`** entry point; adding a language = adding one extractor.

## Plan 4 — Linker (connect the repos)

- **Deterministic cross-repo matching**: matches a UI config URL's path against gateway
  route paths (exact = full confidence; service-prefix = partial).
- Produces the **cross-repo flow graph** (`AnalysisModel` + `Flow`s) — UI node → gateway
  route node, with **confidence scores** on each link.
- **Pluggable Resolver seam**: a clean interface so Claude-assisted resolution of
  ambiguous/indirected links can drop in later without touching the rest.

## Plan 5 — API + Orchestration

- **`analyze()` pipeline** tying it all together: ingest → detect language → parse → link → cache.
- **Automatic language detection** per repo (so the input file stays simple).
- **FastAPI read API:**
  - `GET /projects` — list configured projects
  - `POST /projects/{id}/run` — analyze (always latest) and store
  - `GET /projects/{id}/endpoints` — the endpoint list
  - `GET …/flow` — a chosen endpoint's cross-repo flow
  - `GET …/flow-node` — a node's detail + code reference (powers the popup)

## Plan 6 — Dashboard (the visible product)

- **No-build web dashboard** served directly by the API (no separate toolchain).
- **Endpoint list** with live filter.
- **Cross-repo swimlane view** — one lane per repository; cross-lane arrows are the
  integration points.
- **Step popup** — click any node to see its repo / file:line and the exact code snippet.
- **Confidence surfaced** in the UI (deterministic vs inferred links).

---

## Key technical decisions & corrections

- **Hybrid intelligence model**: tree-sitter does deterministic extraction; Claude is
  reserved (via the Resolver seam) only for genuinely ambiguous cross-repo links — keeps
  token usage and cost proportional to real ambiguity.
- **Real-stack validation corrected the original assumptions** (documented in the design
  spec §12):
  - `edfx-app-ui` is **Angular/TypeScript** (not React).
  - `edfx-api` is **Python/FastAPI**, and its default branch is **`master`** (others are `main`).
  - UI→backend URLs are **indirected** through a config map + a wrapper service — confirming
    cross-repo URL resolution as the core remaining challenge.

## Validation evidence (real EDFX repos)

- **87 inbound endpoints** extracted from `edfx-api` with correct paths + handler locations.
- **Full `endPointConfig` URL map** + outbound call sites extracted from `edfx-app-ui`.
- **44 cross-repo flows** linked deterministically; served over HTTP; rendered in the
  dashboard with working code-ref popups.

## Out of scope for Phase 1 (planned next)

- **Claude resolver wiring** — precise call→route resolution to raise confidence above
  prefix-level matches.
- **Diagrams / narrative / export** — Mermaid flow & sequence diagrams, written write-up,
  Word/PDF export.
- **Live `POST /run`** end-to-end against the private repos (currently validated via a
  seeded model).
- **Phase 2** — MCP publishing (Confluence / Miro / Figma); additional languages (Java, C#).

---

## References

- Design spec: [`docs/2026-06-09-docuproj-design.md`](2026-06-09-docuproj-design.md)
- Implementation plans: [`docs/plans/`](plans/)
