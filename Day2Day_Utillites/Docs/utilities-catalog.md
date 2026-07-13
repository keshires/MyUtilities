# Utilities Catalog & Dashboard

The production utilities in this folder are cataloged in `../utilities.yaml` and
surfaced two ways:

- **Skills** (repo `.claude/skills/`): task runbooks — `stale-entity-refresh`,
  `portfolio-kpi-ops`, `edfx-entity-ops`, `dynamo-batch-update`.
- **Catalog dashboard** — a read-only page listing each utility, a copy-ready command
  builder, required env, and recent run history:

  ```powershell
  cd Day2Day_Utillites
  .\.venv\Scripts\python -m uvicorn dashboard.serve:app --host 127.0.0.1 --port 8021
  # open http://127.0.0.1:8021/app/
  ```

Load-test / Spark POC scripts have been moved to `archive/` (see `archive/README.md`).