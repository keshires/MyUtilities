# EDFX Application Repositories

The EDFX fleet (Moody's View team), grouped by category. DocuProj analyzes these
repos to render cross-repo flows. **Language matters** — DocuProj has extractors for
Python (FastAPI routes, outbound HTTP, DB) and Angular/TypeScript (HTTP client + config);
**.NET has no extractor yet** (see `edfx-bond-api`).

## UI
| Repo | Purpose | Language | Extractor |
|------|---------|----------|-----------|
| `edfx-app-ui` | Main EDFX web application | TypeScript / Angular | ✅ angular |
| `edfx-snippet-ui` | Snippet embeddable UI | TypeScript / Angular | ✅ angular |
| `edfx-bond-screener-ui` | Bond Screener UI | TypeScript / Angular | ✅ angular |

## Public APIs
| Repo | Purpose | Language | Extractor |
|------|---------|----------|-----------|
| `edfx_entity_api` | Entity API | Python | ✅ python |
| `edfx_mapping_service` | Mapping service | Python | ✅ python |
| `edfx-bond-api` | Bond API | **.NET** | ❌ none yet |
| `edfx-snippet-api` | Snippet API | Python | ✅ python |
| `edfx-bond-screener-api` | Bond Screener API | Python | ✅ python |
| `edfx-job-orchestration-api` | Job orchestration API | Python | ✅ python |
| `edfx_model_management_service` | Model management service | Python | ✅ python |

## Private APIs
| Repo | Purpose | Language | Extractor |
|------|---------|----------|-----------|
| `edfx-api` | EDFX gateway API | Python (FastAPI) | ✅ python |
| `edfx-tessera-service` | Tessera API (owns much of the data layer) | Python | ✅ python |
| `edfx-client-financials-api` | Client Financials API | Python | ✅ python |
| `edfx-lgd-service` | LGD API | Python | ✅ python |
| `edfx-preference-service` | User preference service | Python | ✅ python |
| `edfx-bitsight-api` | BitSight Smart Cards API | Python | ✅ python |
| `edfx_scorecard_api` | Scorecard API | Python | ✅ python |

## Background Processes & Pipelines
| Repo | Purpose | Language | Extractor |
|------|---------|----------|-----------|
| `edfx-bond-ingest` | Bond ingestion to OpenSearch | Python | ✅ python |
| `edfx-report-builder` | Report builder | Python | ✅ python |
| `edfx-render-pdf-reports` | PDF report rendering | Node / Puppeteer | ⚠️ partial (TS) |
| `edfx-alerts` | Alerts service | Python | ✅ python |
| `edfx_email_scheduler` | Email scheduler | Python | ✅ python |
| `edfx_financial_statement_collector` | Financial statement collector | Python | ✅ python |

## Notes
- `edfx-api`'s default branch is **`master`**; the rest default to `main`.
- The gateway (`edfx-api`) is thin on direct DB access — it fans out to private
  services (Tessera, LGD, financials, scorecard) which own the Postgres/OpenSearch data layers.
- A given flow (e.g. `/edfx/v2/portfolios/list`) typically traverses: **UI → edfx-api →
  a private service (e.g. Tessera) → datastore (Postgres)**. Tracing that full chain is the
  forward-provenance capability (see `docs/plans/`).
- The sample `projects/edfx-flow.json` covers only the first-hop slice; expand it to the
  chain repos needed for a given flow.