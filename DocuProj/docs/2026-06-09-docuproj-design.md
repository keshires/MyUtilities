# DocuProj — Design Spec

**Date:** 2026-06-09
**Status:** Approved design, ready for implementation planning
**Author:** Sham Sunder Keshireddy (with Claude)

---

## 1. Purpose

DocuProj ingests a list of GitHub repositories, clones them, and analyzes how they
fit together so an engineer can **pick an API endpoint and see its complete flow —
from the request, through the gateway, into every downstream repository it touches**,
with clickable code references at each step. It also generates diagrams and a written
narrative suitable for documentation, and (later) publishes those to Confluence, Miro,
and Figma.

The headline value is **making cross-repository integration boundaries visible**.

### Canonical sample input (the EDFX flow)

The first real target is the EDFX service fleet:

```
https://github.com/moodysanalytics/edfx-app-ui            (React/TS front-end)
https://github.com/moodysanalytics/edfx-api               (gateway API)
https://github.com/moodysanalytics/edfx_entity_api        (entity service)
https://github.com/moodysanalytics/edfx-client-financials-api  (financials service)
https://github.com/moodysanalytics/edfx-tessera-service   (service)
https://github.com/moodysanalytics/edfx-report-builder    (report builder)
```

Typical flow to render: `edfx-app-ui` → `edfx-api` → `edfx_entity_api` /
`edfx-client-financials-api`.

---

## 2. Key decisions (resolved during brainstorming)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Intelligence model | **Hybrid** | tree-sitter extracts structural facts deterministically; Claude reasons only over ambiguous cross-repo links + narrative. Reliable *and* capable. |
| Target languages | Python, TypeScript/TSX, Java, C# | The EDFX fleet and general use are polyglot. One tree-sitter framework, per-language extractor plugins. |
| Implementation | **Python engine + TS/React frontend** | Python for parsing/analysis/orchestration (FastAPI API); React/TS for the dashboard. Clean separation, two focused toolchains. |
| Step-detail UX | **Modal popup** | Flow takes the full canvas; clicking a step opens a popup with description + code lines (req 8, verbatim intent). |
| Flow layout | **Cross-repo swimlanes** | One lane per repo; every arrow that crosses a lane is an integration point — makes req's headline goal the visual star. |
| Sequence diagram | **Generated export** | Mermaid `sequenceDiagram`, on request (req 3e). Not the in-dashboard primary view. |
| Branch selection | **Per-repo default + dashboard override** | Input file gives a default branch per repo; dashboard shows a per-repo dropdown to override before a run (req 2). |
| Input file format | **JSON** | `{project, repos:[{url, folder, branch}]}` (req 1 — maps each repo to a folder). |
| Cache strategy | **Content-addressed by `(commit SHA + analyzer version)`** | Resolves the req-4b/req-5 tension: always fetch latest, reuse cache when nothing changed, re-analyze only what changed. |
| Repo auth / clone | **Plain `git` (works today)** | Git Credential Manager is already authenticated to the private `moodysanalytics` org (`git ls-remote` succeeds). No MCP required to clone. |
| External MCPs | **Phase 2** | No MCP servers are configured yet (`mcpServers: []`). GitHub/Confluence/Miro/Figma all need setup. Deferred so core analysis ships first. |
| Diagram/publish tools | Miro **and** Figma are publish targets; Confluence publishes the write-up | All gated behind explicit user confirmation + MCP configuration (Phase 2). |
| Export | Word via `python-docx`, PDF via `weasyprint` | User picks Word or PDF (req 11). |

---

## 3. Architecture

```
                          repo-list (project.json)
                                   │
                          ┌────────▼─────────┐
                          │     Ingestor     │  git clone/fetch, branch resolve,
                          │  (skill-backed)  │  always-latest, workspace layout
                          └────────┬─────────┘
                                   │ source trees @ pinned SHA
                          ┌────────▼─────────┐
                          │     Parsers      │  tree-sitter per language →
                          │ (per-language)   │  endpoints, functions, calls,
                          └────────┬─────────┘  imports, outbound HTTP calls
                                   │ per-repo facts
                          ┌────────▼─────────┐
                          │     Linker       │  join outbound calls → inbound
                          │ (determ.+Claude) │  routes across repos → graph
                          └────────┬─────────┘
                                   │ Analysis Model (§4)
                          ┌────────▼─────────┐
                          │      Cache       │  keyed by (SHA + analyzer version)
                          └────────┬─────────┘
                                   │
                          ┌────────▼─────────┐
                          │   API server     │  FastAPI: projects, endpoints,
                          │                  │  flows, step detail, jobs
                          └────────┬─────────┘
                                   │ HTTP/JSON
                          ┌────────▼─────────┐
                          │   Dashboard      │  React/TS: endpoint list →
                          │                  │  swimlane flow → step popup →
                          └──────────────────┘  diagrams / narrative / export
```

### Component responsibilities

- **Ingestor** — Reads `project.json`. For each repo: clone if absent, else `git fetch`;
  checkout the selected branch (dashboard override → file default → repo default); record
  resolved HEAD SHA. Clones live in `DocuProj/.workspace/<project>/<folder>` (gitignored).
  Always fetches latest before a run (req 5). *What it depends on:* `git`, the input file.
  *Interface:* `ingest(project.json) -> [{repo, folder, branch, sha, path}]`.

- **Parsers** — One extractor per language, all built on tree-sitter. Each consumes a
  source tree and emits per-repo **facts**: endpoints/routes (with method, path, handler
  location), function definitions, intra-repo calls, imports, and **outbound HTTP calls**
  (client calls with a URL/path literal or template). *Interface:*
  `parse(repoPath, language) -> RepoFacts`. Adding a language = adding one extractor; no
  other component changes.

- **Linker** — Builds the cross-repo graph. Deterministic pass first: match an outbound
  call's path/method to an inbound route in another repo. Ambiguous or templated cases go
  to Claude, which returns a link + **confidence score**. Front-end → backend links use the
  same mechanism (UI `api.post('/path')` → gateway route). *Interface:*
  `link(allRepoFacts) -> AnalysisModel`.

- **Cache** — Content-addressed store keyed by `(repo SHA + analyzer version)`. On a run,
  if every repo's SHA and the analyzer version are unchanged, the cached `AnalysisModel`
  is served with no re-parsing and no Claude tokens. Otherwise only changed repos are
  re-parsed and the graph re-linked. *Interface:* `get(key)`, `put(key, model)`.

- **API server (FastAPI)** — Read endpoints over the Analysis Model; job endpoints to
  generate a diagram, a narrative, or an export. *Interface:* see §5.

- **Dashboard (React/TS)** — Endpoint list (req 6) → click endpoint → swimlane flow (req 7)
  → click step → modal popup with description + code lines (req 8) → buttons to generate
  diagrams (req 9), write-up (req 10), and export Word/PDF (req 11).

---

## 4. Data model (the stable contract)

Everything downstream reads **only** this model. It is the first thing built and stabilized.

```jsonc
Project  { id, name, repos: [RepoRef] }
RepoRef  { url, folder, branch, sha }

Endpoint { id, repo, method, path, handlerRef: CodeRef, language }

FlowNode { id, repo, label, kind: "ui"|"route"|"fn"|"outbound", codeRef: CodeRef }
FlowEdge { from: nodeId, to: nodeId, kind: "calls"|"http", confidence: 0.0-1.0 }
Flow     { endpointId, nodes: [FlowNode], edges: [FlowEdge] }   // one per endpoint

CodeRef  { repo, file, line, snippet }    // powers the step popup (req 8)
```

- `confidence` lets the dashboard distinguish deterministic links from Claude-inferred ones
  (e.g. dashed edge for low confidence).
- `CodeRef.snippet` is the few lines shown in the popup; `file`+`line` make it a clickable
  reference.

---

## 5. API surface (Phase 1)

```
GET  /projects                       -> [Project]
POST /projects/{id}/run              -> triggers ingest+analyze (always latest); returns job
GET  /projects/{id}/endpoints        -> [Endpoint]            (req 6)
GET  /endpoints/{id}/flow            -> Flow                  (req 7)
GET  /flow-nodes/{id}                -> FlowNode + CodeRef    (req 8 popup)
POST /endpoints/{id}/diagram         -> { mermaid }           (req 9, on request)
POST /endpoints/{id}/writeup         -> { markdown }          (req 10)
POST /endpoints/{id}/export          -> { file } body:{format:"docx"|"pdf"}  (req 11)
```

---

## 6. Skills (req 4 — minimize tokens)

Repetitive, deterministic work is implemented as skills/CLI steps, **not** LLM calls:

- `clone-pull-latest` — clone/fetch + branch checkout + SHA capture (req 4a, req 5).
- `extract-endpoints-<lang>` — run the per-language tree-sitter extractor.
- `cache-get` / `cache-put` — SHA-keyed cache access (req 4b).
- `render-mermaid` — model → Mermaid flow/sequence text.
- `export-doc` — Markdown → Word/PDF.

Claude is invoked **only** for: (a) ambiguous cross-repo link inference, (b) narrative
write-up prose. This keeps token usage proportional to genuinely fuzzy work.

---

## 7. Diagrams, narrative, export

- **In-dashboard flow:** cross-repo swimlanes, rendered from the Analysis Model.
- **Flow diagram & sequence diagram:** Mermaid (`flowchart` / `sequenceDiagram`), generated
  **on request** (req 9, req 3e). Renders in-browser; exportable as image. No MCP needed.
- **Narrative write-up:** Markdown generated from the flow model + Claude prose, describing
  the request path, each hop, and the integration points (req 10).
- **Export:** Word (`python-docx`) or PDF (`weasyprint`), user's choice (req 11).

---

## 8. Phasing

### Phase 1 — Core product (no external MCP)
Ingest → parse → link → cache → dashboard (endpoint list, swimlane flow, step popup) →
Mermaid flow + sequence on request → narrative → Word/PDF export. Validated against the 6
EDFX repos.

**Phase 1 MVP slice (build this first):** one real `edfx-app-ui` endpoint, traced to a
complete `UI → edfx-api → downstream` swimlane with working step popups. This exercises the
hardest component (cross-repo Linker) earliest and proves the full vertical before breadth.

### Phase 2 — MCP enrichment
- **GitHub MCP** — PR/commit metadata enrichment on nodes.
- **Confluence/Atlassian MCP** — publish the write-up (req 3a).
- **Miro MCP** — push a generated board (req 9), on user confirmation.
- **Figma MCP** — publish a frame, on user confirmation (req 3c).

All Phase-2 features are gated behind explicit user confirmation and require configuring the
respective MCP server (none exist today).

---

## 9. Workspace & repo layout

```
DocuProj/
  engine/            # Python: ingestor, parsers, linker, cache, FastAPI app
  dashboard/         # React/TS frontend
  skills/            # clone-pull-latest, extract-endpoints-*, cache-*, render-mermaid, export-doc
  projects/          # saved project.json inputs (e.g. edfx-flow.json)
  .workspace/        # gitignored: cloned repos + cache artifacts
  docs/              # generated write-ups / exports
```

---

## 10. Risks & open items

- **Cross-repo linking accuracy** is the core technical risk. Outbound calls use templated
  URLs, base-URL config, and indirection. Mitigation: deterministic match where possible,
  Claude with confidence scoring elsewhere, surface confidence in the UI. The MVP slice
  exists to de-risk this first.
- **Service base-URL resolution** — mapping `api.post('/v2/financials')` to the right repo
  may require reading config/env/service-discovery. To be detailed in the implementation plan.
- **Language coverage depth** — Phase 1 targets the constructs needed for the EDFX flow
  (React HTTP clients, the gateway framework, downstream route declarations); exhaustive
  per-language coverage grows iteratively.
- **MCP availability** — all external publishing depends on servers not yet configured;
  isolated to Phase 2 so it never blocks core value.

---

## 11. Out of scope (YAGNI)

- Runtime/dynamic tracing (this is static analysis).
- Editing or modifying the analyzed repos.
- Authn/multi-user dashboard hosting (local single-user tool for now).
- Exhaustive language support beyond what the target flows require.
