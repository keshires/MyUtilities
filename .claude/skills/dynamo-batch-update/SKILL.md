---
name: dynamo-batch-update
description: Use when batch-updating a field across DynamoDB records (e.g. the CreatedBy migration) — scanning a table for records matching a value and writing a new value in parallel, with a dry-run safety gate.
---

# DynamoDB Batch Update

Tool: `Day2Day_Utillites/DynamoDB_BatchUpdate_CreatedBy.py`. Run from that folder with
`.\.venv\Scripts\python`. Canonical env is in `Day2Day_Utillites/utilities.yaml`.

## How to run
This script is **configured by editing in-script constants** (table name, partition/sort
keys, `CURRENT_VALUE_TO_FIND` → `NEW_VALUE_TO_SET`, `ENVIRONMENT`, `DRY_RUN`), not CLI flags.

1. Edit the config block at the top of the script for your table and value mapping.
2. Keep `DRY_RUN = True`; run and review the sample records + counts it prints:
   `python DynamoDB_BatchUpdate_CreatedBy.py`
3. Only after the dry-run output looks correct, set `DRY_RUN = False` and re-run.

## Safety
DESTRUCTIVE when `DRY_RUN = False` — it updates prod DynamoDB rows in parallel. Never
skip the dry-run. Confirm the record count matches expectations before the real run.
Runs now log to `logs/dynamodb_batch_update/`.

## Prereqs
AWS credentials resolvable by boto3 (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_DEFAULT_REGION`, or an AWS CLI profile).

## Dashboard
```powershell
cd Day2Day_Utillites
.\.venv\Scripts\python -m uvicorn dashboard.serve:app --host 127.0.0.1 --port 8021
# http://127.0.0.1:8021/app/
```
