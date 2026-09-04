# Planning Document: Custom Entity Cleanup — AWS Batch Job
**Jira:** EDFX-29390  
**Date:** 2026-09-02  
**Author:** Kiran / Karthi  
**Target repo:** `edfx-tessera-service`

---

## 1. Background and Goal

The manual script `financials_delete_custom_entity.py` currently requires a human to run it each month-end to delete Moody's-tenant custom companies from the EDFX Financials service before the monthly metadata refresh. The goal is to convert this into a fully automated, config-driven AWS Batch job that:

- Runs on a monthly schedule (EventBridge cron, before month-end metadata refresh)
- Reads deletion criteria from a new Tessera DB config table (tenant_id + email addresses)
- Deletes eligible custom entities via the EDFX Financials API
- Supports multiple tenant configurations without code changes
- Logs results to CloudWatch (structured JSON via `aws-lambda-powertools` Logger)

Scripts **excluded** from scope: `load_entity_delete_queue.py`, `export_stale_entities_from_excel.py`.

---

## 2. Scheduling Mechanism (Reference: `edfx-portfolio-refresh-batch`)

The pattern confirmed from `edfx-portfolio-refresh-batch/template.yaml`:

```
AWS EventBridge Rule (cron)
        │  BatchParameters { JobDefinition, JobName }
        ▼
AWS Batch Job Queue  →  Batch Job Definition  →  ECS Fargate Container
                                                        │
                                                        ▼
                                              python -m <entrypoint>
```

**Key insight:** EventBridge targets the Batch job queue ARN **directly** — no Lambda intermediary. The `BatchParameters` block in the `AWS::Events::Rule` resource specifies which job definition and job name to submit. The IAM execution role is used by EventBridge to call `batch:SubmitJob` on our behalf.

Our batch job will follow this same pattern with a monthly cron expression (e.g., `cron(0 2 L * ? *)` — 2 AM UTC on last day of each month, adjustable per environment).

---

## 3. Deletion Criteria (Config-Driven Design)

### Current hardcoded approach (script)
```sql
WHERE portfolio_id = 22666
  AND eca.created_date < '2026-07-25'
  AND eca.created_by = 'kiran.sunkara@moodys.com'
  AND e.tenant_id = <hardcoded>
```

### New approach: Single config table in Tessera DB

One row per `(tenant_id, user_email)` pair so individual emails can be enabled/disabled independently. No separate tenant-level table.

---

#### Table: `custom_entity_cleanup_email_config`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `tenant_id` | TEXT NOT NULL | Moody's tenant identifier |
| `user_email` | TEXT NOT NULL | `created_by` filter value |
| `is_active` | BOOLEAN NOT NULL default true | Enable/disable individual email |
| `created_date` | DATETIME NOT NULL | |
| `created_by` | TEXT NOT NULL | |
| `updated_date` | DATETIME nullable | |
| `updated_by` | TEXT nullable | |
| UNIQUE | `(tenant_id, user_email)` | No duplicate email per tenant |

---

**Query logic at job runtime:**
```sql
SELECT tenant_id, array_agg(user_email) AS emails
FROM custom_entity_cleanup_email_config
WHERE is_active = true
GROUP BY tenant_id
```

Then per tenant row (cutoff read from `settings.CLEANUP_CUTOFF_DAYS_OFFSET`):
```sql
SELECT e.external_id
FROM entity e
JOIN entity_custom_data eca ON e.id = eca.entity_id AND e.tenant_id = eca.tenant_id
WHERE e.tenant_id = :tenant_id
  AND e.custom_id IS NOT NULL
  AND eca.created_by = ANY(:emails)
  AND eca.created_date < NOW() - INTERVAL ':cutoff_days_offset days'
```

This replaces the portfolio_id join (that was incidental to the manual process) with a direct entity+custom_data join filtered only by tenant and email(s).

---

## 4. Architecture Overview

```
EventBridge (monthly cron)
        │
        ▼
AWS Batch Job Queue
        │
        ▼
ECS Fargate Container  (tessera-service image, new entrypoint)
        │
        ├── Read custom_entity_cleanup_email_config from Tessera DB
        │       (all rows where is_active = true, grouped by tenant_id)
        │
        ├── For each config row:
        │       ├── Query entity + entity_custom_data → external_ids to delete
        │       ├── Get Moody's SSO token (cached, 15-min expiry via TokenService)
        │       ├── Call DELETE /financials/client/v1/customEntity/{external_id}
        │       │       (parallel, asyncio with semaphore, concurrency=5)
        │       └── On success → insert row into custom_entity_cleanup_audit_log
        │               { tenant_id, external_id, user_email, batch_job_id, deleted_at }
        │
        ├── Log summary to CloudWatch (structured JSON)
        │       { tenant_id, total, succeeded, failed }
        │
        └── Purge audit_log rows older than CLEANUP_AUDIT_RETENTION_DAYS (default 90)
```

---

## 5. Files to Create / Modify

### 5.1 New: Alembic Migration (0111_custom_entity_cleanup_config.py)

**Path:** `alembic/migrations/versions/0111_custom_entity_cleanup_config.py`

Creates the email config table and audit log table in a single migration. Migration number follows `0110_entity_presence_indexes.py` (current latest).

```python
# Pseudocode
op.create_table('custom_entity_cleanup_email_config',
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('tenant_id', sa.Text(), nullable=False),
    sa.Column('user_email', sa.Text(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
    sa.Column('created_date', sa.DateTime(), nullable=False),
    sa.Column('created_by', sa.Text(), nullable=False),
    sa.Column('updated_date', sa.DateTime(), nullable=True),
    sa.Column('updated_by', sa.Text(), nullable=True),
    sa.UniqueConstraint('tenant_id', 'user_email', name='uq_cleanup_email_tenant'),
)

op.create_table('custom_entity_cleanup_audit_log',
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('tenant_id', sa.Text(), nullable=False),
    sa.Column('external_id', sa.Text(), nullable=False),
    sa.Column('user_email', sa.Text(), nullable=False),
    sa.Column('batch_job_id', sa.Text(), nullable=True),   # AWS_BATCH_JOB_ID env var
    sa.Column('deleted_at', sa.DateTime(), nullable=False),
    sa.Column('created_date', sa.DateTime(), nullable=False),
)
```

### 5.2 New: SQLAlchemy Models

**Paths:**
- `app/db/models/custom_entity_cleanup_email_config_model.py`
- `app/db/models/custom_entity_cleanup_audit_log_model.py`

Both use the existing `DatabaseModelBase` pattern. No FK relationship — `tenant_id` is a plain text column on the email config model.

### 5.3 New: Repository Methods

**Path:** `app/db/repositories/custom_entity_repository.py`

Add methods:
1. `get_cleanup_configs()` — queries `custom_entity_cleanup_email_config`, returns active `(tenant_id, [emails])` rows grouped by tenant
2. `get_entities_for_cleanup(tenant_id, emails, cutoff_days_offset) -> List[str]` — returns `external_id` list; `cutoff_days_offset` passed in from `settings.CLEANUP_CUTOFF_DAYS_OFFSET`
3. `insert_audit_log(tenant_id, external_id, user_email, batch_job_id, deleted_at)` — inserts one success record into `custom_entity_cleanup_audit_log`
4. `purge_audit_log(retention_days: int)` — deletes rows from `custom_entity_cleanup_audit_log` where `deleted_at < NOW() - INTERVAL retention_days days`

### 5.4 New: `delete_custom_entity()` in `ClientFinancials`

**Path:** `app/clients/financials/client_financials.py`

The endpoint `DELETE /financials/client/v1/customEntity/{entityId}` already exists in `edfx-client-financials-api`. No new endpoint needs to be created. We only need to add a thin client method in tessera-service that calls it:

```python
async def delete_custom_entity(self, external_id: str) -> bool:
    url = f'customEntity/{external_id}'
    status, _ = await self.delete(url)
    return status == httpx.codes.OK
```

`ClientBase.delete()` handles the aiohttp session, request logging, timing, and error logging. The `prefix_url` is already set to `EDFX_SERVICE_URL + '/financials/client/v1'` in `ClientFinancials.__init__`, so the full URL resolves to `DELETE /financials/client/v1/customEntity/{external_id}` automatically.

Returns `True` on HTTP 200 (success) — the batch job uses this to decide whether to insert the audit log row. The existing `delete_custom_financials()` is a different method that deletes financial *statement data*, not the entity record itself.

### 5.4a Fix Required: `edfx-client-financials-api` — Allow Technical User to Delete Any Entity

**Repo:** `edfx-client-financials-api`  
**File:** `app/services/custom_entity_service.py`  
**Method:** `delete_custom_entity()` — line 344  
**Change location:** Lines 365–368

#### Root Cause

When an entity is deleted via `DELETE /financials/client/v1/customEntity/{entityId}`, the service enforces that only the entity's original creator can delete it:

```python
# Line 363 — reads the "sub" stored at entity creation time
entity_owner = entity.get("created", {}).get("by", "")

# Line 366 — reads the "sub" from the current DELETE request's JWT
# Raises 403 if they don't match
if entity_owner != current_user_id:                     # line 366
    raise HTTPException(status_code=403,
                        detail=f"Cannot delete entity created by a different user")
```

The batch job authenticates as `TESSERA_TECHNICAL_USER_LOGIN` (super-user), but the entities were originally created by individual user accounts (e.g., `kiran.sunkara@moodys.com`). So the `sub` values will never match, and every delete call will return a 403.

#### Existing Hook: `token_data.is_admin()`

`app/authentication/token_data.py` (line 123) already has a helper:

```python
def is_admin(self) -> bool:
    is_admin: bool = self.subject() == settings.TESSERA_TECHNICAL_USER_LOGIN
    return is_admin
```

This returns `True` whenever the caller's JWT `sub` equals `TESSERA_TECHNICAL_USER_LOGIN`.

#### Fix

In `app/services/custom_entity_service.py`, line 366, add `and not self.token.is_admin()` to the ownership check:

```python
# BEFORE (line 366)
if entity_owner != current_user_id:
    raise HTTPException(status_code=403,
                        detail=f"Cannot delete entity created by a different user")

# AFTER
if entity_owner != current_user_id and not self.token.is_admin():
    raise HTTPException(status_code=403,
                        detail=f"Cannot delete entity created by a different user")
```

This allows `TESSERA_TECHNICAL_USER_LOGIN` to bypass the owner check while all regular users remain restricted to deleting only their own entities.

**No other files need to change in `edfx-client-financials-api`.**

---

### 5.4b New: `retain` Flag — `entity_custom_data` Table + Insert Path

**Decision:** Confirmed in scope. A new `retain` boolean column is added to `entity_custom_data`. Default is `true` (retain — safe for all existing entities). Only rows where `retain = false` are eligible for batch deletion. A DBA/admin explicitly sets `retain = false` for entities that should participate in monthly cleanup.

---

#### Where `entity_custom_data` rows are created

All inserts/updates go through a single service in `edfx-tessera-service`:

**File:** `app/services/entity/entity_customizations_service.py`  
**Repository:** `app/db/repositories/entity_custom_data_repository.py`  
**Model:** `app/db/models/entity_custom_data_model.py`

The three insert call sites in `entity_customizations_service.py`:

| Method | Line | Trigger |
|---|---|---|
| `upsert_profile_custom_data()` | line 149 | Standard entity profile create/update |
| `upsert_custom_data_peer_group_id()` | line 186 | Peer group assignment |
| `upsert_custom_parent_group_support()` | line 209 | Parent group support process |

The bulk path via `bulk_upsert_entities_custom_data()` in the repository (line 59) handles batch/import flows.

---

#### Changes Required

**1. Alembic migration (new — add to migration `0111` or a separate `0113`)**

```python
op.add_column('entity_custom_data',
    sa.Column('retain', sa.Boolean(), nullable=False, server_default='true')
)
```

Default `true` — all existing entities are **retained** (safe default). A DBA/admin must explicitly set `retain = false` for entities that should be cleaned up monthly.

**2. SQLAlchemy model**  
**File:** `app/db/models/entity_custom_data_model.py`  
Add after line 32 (`updated_by` column):
```python
retain = Column(Boolean, nullable=False, server_default=text("true"))
```

**3. Repository — `bulk_upsert_entities_custom_data()`**  
**File:** `app/db/repositories/entity_custom_data_repository.py` — line 59  
The `on_conflict_do_update` set dict (lines 65–79) must **not** include `retain` in the update columns — i.e., do not overwrite a user-set `retain=false` on upsert conflict. No code change needed here as long as `retain` is simply omitted from the upsert set dict.

**4. Batch job query — `get_entities_for_cleanup()`**  
**File:** `app/db/repositories/custom_entity_cleanup_repository.py` (new, step 5 in impl sequence)  
The entity query must add a filter to exclude retained entities:
```sql
AND eca.retain = false
```
So the full query becomes:
```sql
SELECT e.external_id
FROM entity e
JOIN entity_custom_data eca ON e.id = eca.entity_id AND e.tenant_id = eca.tenant_id
WHERE e.tenant_id = :tenant_id
  AND e.custom_id IS NOT NULL
  AND eca.created_by = ANY(:emails)
  AND eca.created_date < NOW() - INTERVAL ':cutoff_days_offset days'
  AND eca.retain = false   -- only delete entities explicitly opted-in to cleanup
```

**5. API — expose `retain` field**  
Handled via the new bulk admin API in section 5.10. No additional changes needed here.

---

### 5.5 New: Batch Service

**Path:** `app/services/aws/batch/custom_entity_cleanup_batch_service.py`

Extends `AwsBatchBaseService` (same pattern as `AuditTrailExportBatchService`):
```python
class CustomEntityCleanupBatchService(AwsBatchBaseService):
    def __init__(self):
        super().__init__(
            job_definition=settings.BATCH_JOB_DEFINITION_CUSTOM_ENTITY_CLEANUP,
            job_queue=settings.BATCH_JOB_QUEUE_CUSTOM_ENTITY_CLEANUP,
        )
    def submit(self) -> str:
        return self.submit_job(job_name="CustomEntityCleanup", params={}, tags={})
```

This service is used if the job needs to be triggered *programmatically* from another service. For the scheduled invocation, EventBridge calls Batch directly.

### 5.6 New: Batch Job Entrypoint

**Path:** `app/batch/custom_entity_cleanup/main.py`

The container entrypoint for this batch job. Contains the main execution loop:

```python
async def run():
    logger = Logger(service="custom-entity-cleanup")
    db_session = get_db_session()
    repo = CustomEntityRepository(db_session)
    client = ClientFinancials(settings)
    token_service = TokenService()

    configs = repo.get_cleanup_configs()
    logger.info("Loaded cleanup configs", extra={"count": len(configs)})

    for config in configs:
        external_ids = repo.get_entities_for_cleanup(
            config.tenant_id, config.email_addresses, settings.CLEANUP_CUTOFF_DAYS_OFFSET
        )
        logger.info("Entities to delete", extra={
            "tenant_id": config.tenant_id, "count": len(external_ids)
        })

        token = await token_service.get_technical_user_token()
        results = await delete_entities_parallel(client, token, external_ids)

        logger.info("Deletion complete", extra={
            "tenant_id": config.tenant_id,
            "succeeded": results.succeeded,
            "failed": results.failed,
            "failed_ids": results.failed_ids,
        })
```

Parallel deletion uses `asyncio.gather()` with a semaphore (default concurrency: 5, matching the manual script's ThreadPoolExecutor worker count) rather than `ThreadPoolExecutor` since `ClientFinancials` is async (`httpx`).

### 5.7 New: Dockerfile for Cleanup Batch Job

**Path:** `Dockerfile.custom_entity_cleanup` (or a dedicated directory)

Based on the tessera-service base image. Sets `ENTRYPOINT ["python", "-m", "app.batch.custom_entity_cleanup.main"]`.

### 5.8 New: SAM/CloudFormation Template

**Path:** `infrastructure/custom_entity_cleanup_batch/template.yaml`

Resources:
- `AWS::Batch::JobDefinition` — `EDFXCustomEntityCleanupBatch-${EnvironmentNumber}`
- `AWS::Batch::JobQueue` — reuse the shared `EDFXComputeEnvironment-${EnvironmentNumber}` (same as portfolio-refresh-batch)
- `AWS::Events::Rule` — monthly schedule targeting the job queue via `BatchParameters`

Parameters: `EnvironmentCode`, `EnvironmentNumber`, `BatchJobScheduleExpression` (default: `cron(0 2 L * ? *)`)

### 5.9 Modify: `settings.py`

**Path:** `app/configuration/settings.py`

Add under the `# AWS Batch` section:
```python
BATCH_JOB_DEFINITION_CUSTOM_ENTITY_CLEANUP: Optional[str]
BATCH_JOB_QUEUE_CUSTOM_ENTITY_CLEANUP: Optional[str]
```

Add a new `# Custom Entity Cleanup` section:
```python
# Custom Entity Cleanup
CLEANUP_CUTOFF_DAYS_OFFSET: int = 30     # delete entities created more than N days ago
CLEANUP_AUDIT_RETENTION_DAYS: int = 90   # audit log rows older than this are purged each run
CLEANUP_DELETE_CONCURRENCY: int = 5      # parallel DELETE API calls per tenant
```

### 5.10 New: Admin API — Bulk Update `retain` Flag

**Repo:** `edfx-tessera-service`

The production team sends a list of entity external IDs each month before the batch job runs. This API receives that list and sets `retain = false` on the matching `entity_custom_data` rows for the calling tenant, making them eligible for cleanup. All other entities remain `retain = true` (default — never deleted).

#### Route

**File:** `app/routers/v1/entity_customizations_route.py`  
**Prefix:** `RouteConfiguration.TESSERAUI_CONTEXT_URL + RouteConfiguration.VERSION_1_URL`  
i.e. `/tesseraui/v1`

New endpoint to add to this router:
```
PATCH /tesseraui/v1/customEntity/retainFlag
```

New route constant to add in `route_configuration.py`:
```python
TESSERAUI_CUSTOM_ENTITY_RETAIN_FLAG = '/customEntity/retainFlag'
```

#### Request / Response

```python
# Request body
class UpdateRetainFlagRequest(BaseModel):
    entity_ids: List[str]   # comma-separated list accepted as a JSON array
    retain: bool            # true = retain (exclude from cleanup), false = allow deletion

# Response body
class UpdateRetainFlagResponse(BaseModel):
    updated: int            # number of rows successfully updated
    not_found: List[str]    # external_ids that had no matching entity_custom_data row
```

The caller passes `retain: false` to opt entities in to cleanup, or `retain: true` to re-protect them.

#### Service

**File:** `app/services/entity/entity_customizations_service.py`

New method:
```python
def bulk_update_retain_flag(self, external_ids: List[str], retain: bool) -> UpdateRetainFlagResponse:
    tenant_id = self.app_context.get_effective_tenant_id()
    rows = self.entity_custom_data_repository.find_by_external_ids(external_ids)
    found_ids = {r.external_id for r in rows}
    not_found = [eid for eid in external_ids if eid not in found_ids]
    for row in rows:
        row.retain = retain
        row.updated_by = self.app_context.user_dto.email
    self.entity_custom_data_repository.bulk_update_retain(rows)
    return UpdateRetainFlagResponse(updated=len(rows), not_found=not_found)
```

#### Repository

**File:** `app/db/repositories/entity_custom_data_repository.py`

New method:
```python
def bulk_update_retain(self, rows: List[EntityCustomDataModel]) -> None:
    for row in rows:
        row.updated_date = datetime.now(timezone.utc)
    self.db_session.commit()
```

`find_by_external_ids()` already exists at line 20 of the same file — reused directly.

#### Auth / Access Control

- Requires a valid SSO token (standard tessera-service auth middleware — no change needed)
- Scoped to the calling user's tenant via `get_effective_tenant_id()` — one tenant cannot update another tenant's entities
- No additional role check in v1; restrict to admin role in v2 if needed

---

## 6. SSO / Authentication

Reuse the existing `TokenService.get_technical_user_token()` pattern:
- Credentials: `TESSERA_TECHNICAL_USER_LOGIN` + `TESSERA_TECHNICAL_USER_PASSWORD` (already in `settings.py`)
- Token expiry: 15 minutes (`TESSERA_TECHNICAL_USER_TOKEN_EXPIRY = 900`) cached via Redis
- The batch container will have access to the Redis cache (same VPC/subnet as tessera-service)

No new credentials needed.

---

## 7. Audit / Observability

### Tessera DB Audit Log (`custom_entity_cleanup_audit_log`)

| Column | Notes |
|---|---|
| `id` | PK auto-increment |
| `tenant_id` | Which tenant this deletion was for |
| `external_id` | The entity external ID that was deleted |
| `user_email` | The config email that matched this entity |
| `batch_job_id` | AWS Batch job ID — read from `AWS_BATCH_JOB_ID` env var (nullable — absent in local runs) |
| `deleted_at` | Timestamp of successful API response |
| `created_date` | Row insertion timestamp |

- **Only successful deletions are logged** — failures are surfaced in CloudWatch only
- **Purge policy**: at the end of every job run, rows where `deleted_at < NOW() - INTERVAL N days` are deleted. `N` = `CLEANUP_AUDIT_RETENTION_DAYS` in `settings.py` (default 90)
- `AWS_BATCH_JOB_ID` is automatically injected by AWS Batch into the container environment — no manual plumbing needed

### CloudWatch Logs

All output via `aws-lambda-powertools` Logger (structured JSON) goes to the ECS task log group. Each run logs:
- Config rows loaded (tenant count)
- Per-tenant: entities found, succeeded, failed
- Audit log purge: how many rows were deleted
- Any unhandled exceptions with stack traces

---

## 8. Implementation Sequence

| Step | File | Description |
|------|------|-------------|
| 1a | `alembic/migrations/versions/0111_custom_entity_cleanup_config.py` | Create 2 tables: email config, audit log |
| 1b | `alembic/migrations/versions/0112_seed_custom_entity_cleanup_config.py` | Seed initial email config rows per environment |
| 2 | `app/db/models/custom_entity_cleanup_email_config_model.py` | SQLAlchemy model for email config (`tenant_id` + `user_email`) |
| 3 | `app/db/models/custom_entity_cleanup_audit_log_model.py` | SQLAlchemy model for audit log |
| 4 | `app/db/repositories/custom_entity_repository.py` | Add `get_cleanup_configs()`, `get_entities_for_cleanup()`, `insert_audit_log()`, `purge_audit_log()` |
| 4a | `edfx-client-financials-api` → `app/services/custom_entity_service.py` line 366 | Add `and not self.token.is_admin()` to bypass 403 for technical user (see section 5.4a) |
| 4b | `edfx-tessera-service` → `app/db/models/entity_custom_data_model.py` | Add `retain = Column(Boolean, nullable=False, server_default=text("true"))` column |
| 4c | Alembic migration (new file) | `op.add_column('entity_custom_data', retain BOOLEAN NOT NULL DEFAULT true)` — do NOT include `retain` in `bulk_upsert` conflict set dict (see section 5.4b) |
| 4d | `app/routers/route_configuration.py` | Add `TESSERAUI_CUSTOM_ENTITY_RETAIN_FLAG = '/customEntity/retainFlag'` constant |
| 4e | `app/routers/v1/entity_customizations_route.py` | Add `PATCH /tesseraui/v1/customEntity/retainFlag` endpoint (see section 5.10) |
| 4f | `app/services/entity/entity_customizations_service.py` | Add `bulk_update_retain_flag(external_ids, retain)` method |
| 4g | `app/db/repositories/entity_custom_data_repository.py` | Add `bulk_update_retain(rows)` method; reuse existing `find_by_external_ids()` |
| 5 | `app/clients/financials/client_financials.py` | Add `delete_custom_entity(external_id)` method |
| 7 | `app/configuration/settings.py` | Add `BATCH_JOB_DEFINITION_CUSTOM_ENTITY_CLEANUP`, `BATCH_JOB_QUEUE_CUSTOM_ENTITY_CLEANUP`, `CLEANUP_CUTOFF_DAYS_OFFSET`, `CLEANUP_AUDIT_RETENTION_DAYS`, `CLEANUP_DELETE_CONCURRENCY` |
| 8 | `app/batch/custom_entity_cleanup/main.py` | Batch entrypoint — delete loop + audit insert + purge |
| 9 | `app/services/aws/batch/custom_entity_cleanup_batch_service.py` | `AwsBatchBaseService` extension |
| 10 | `Dockerfile.custom_entity_cleanup` | Container definition |
| 11 | `infrastructure/custom_entity_cleanup_batch/template.yaml` | SAM/CF template (Batch job + EventBridge rule) |
| 12 | `samconfig.toml` (or equivalent) | Env-specific parameter overrides |

---

## 9. Open Questions / Decisions Needed

| # | Question | Current Assumption |
|---|---|------|
| 1 | **Schedule time**: When exactly should the job run relative to the metadata refresh? | `cron(0 2 L * ? *)` — 2 AM UTC last day of month. Confirm with ops team. |
| 2 | **Tessera DB config seeding**: Who populates the config table? | Dev team seeds initial `custom_entity_cleanup_email_config` rows via a dedicated Alembic migration script (`0112_seed_custom_entity_cleanup_config.py`) created alongside the table migration. Config data is version-controlled and deployed automatically as part of the standard Alembic upgrade. No DBA manual inserts, no admin UI. |
| 3 | **Retention flag**: Decided. | Add `retain` boolean column (default `true`) to `entity_custom_data` table. Only rows with `retain = false` are eligible for batch deletion — DBA/admin explicitly opts entities in. Column added via Alembic migration; `bulk_upsert` must NOT overwrite it on conflict. Batch query filters `AND eca.retain = false`. API exposure deferred to v2. See section 5.4b. |
| 4 | **Auth approach**: Decided. | `TESSERA_TECHNICAL_USER_LOGIN` will be used to authenticate and perform the deletions. Same pattern as delete_draft_loans. |
| 5 | **Shared Batch queue or dedicated?** | Reuse shared `EDFXComputeEnvironment-${EnvironmentNumber}` (same as portfolio-refresh). Dedicated queue not needed — low-priority monthly job. |
| 6 | **CircleCI**: Decided. | Batch job build and deploy is part of the tessera-service CircleCI pipeline. No separate pipeline needed. |
| 7 | **ECR image**: Separate image (`edfx/edfx-custom-entity-cleanup-batch`) or reuse tessera-service image with different entrypoint? | Separate image is cleaner. Matches portfolio-refresh-batch pattern. |

