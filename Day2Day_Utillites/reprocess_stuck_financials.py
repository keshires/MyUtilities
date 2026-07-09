"""
Find (and optionally re-post) entities whose ``financials_process_status`` is NOT
``Completed`` — i.e. stuck in ``Failed`` / ``Aborted`` / ``Started`` /
``Completed with errors`` (and NULL anomalies) — to force a financials retry and to
validate whether they have been stuck *forever and never retried*.

The signal for "never retried" is ``financials_process_status_date`` — if it hasn't
moved in months, the process was never re-attempted.

Three modes:

  report   (default, read-only)
      Write a per-entity CSV (status, status_date, days_in_state, age bucket, ids,
      pd_last_known_date) plus a tenant-wise summary CSV. Proves how long each has
      been stuck.

  --submit
      Re-post the target entities via ``refreshEntities`` (one external_id per
      request, N workers, checkpointed) to trigger a fresh financials process.
      Writes a before-snapshot so a later --recheck-from can measure transitions.

  --recheck-from <snapshot.json>
      Re-query the snapshot's entities and report how many moved to Completed /
      Completed with errors (retry worked) vs still stuck (chronic failure).

Examples:
  python reprocess_stuck_financials.py --entity-type custom
  python reprocess_stuck_financials.py --entity-type custom --include-null-status
  python reprocess_stuck_financials.py --entity-type custom --submit --workers 8
  python reprocess_stuck_financials.py --recheck-from logs/<snapshot>.json
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

import refresh_stale_non_public_entities as rf
from project_paths import output_dir, resolve_cli_artifact

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Not-"Completed" statuses worth a financials retry. "Completed with errors" is
# included per requirement; NULL is opt-in (10M standard private entities have a
# NULL status and are NOT candidates).
DEFAULT_TARGET_STATUSES = ("Failed", "Aborted", "Started", "Completed with errors")

CSV_FIELDS = [
    "external_id",
    "custom_id",
    "tenant_id",
    "financials_process_status",
    "financials_process_status_date",
    "days_in_state",
    "age_bucket",
    "financials_process_id",
    "financials_type",
    "pd_last_known_date",
    "as_of_date",
    "financial_stmt_date",
]

TENANT_CSV_FIELDS = [
    "tenant_id",
    "total",
    "failed",
    "aborted",
    "started",
    "completed_with_errors",
    "null_status",
    "chronic_gt_180d",
    "oldest_status_date",
]


def age_bucket(days: int | None) -> str:
    if days is None:
        return "unknown"
    if days >= 180:
        return ">180d"
    if days >= 90:
        return "90-180d"
    if days >= 30:
        return "30-90d"
    return "<30d"


def _iso(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def build_query(
    mode: "rf.EntityRefreshMode",
    *,
    tenant_id: str | None,
    include_null: bool,
    limit: int | None,
) -> str:
    tenant_clause = "e.tenant_id = $2::text" if tenant_id else "e.tenant_id <> ALL($2::text[])"
    custom_clause = mode.custom_id_clause.replace("custom_id", "e.custom_id")
    status_clause = "ecd.financials_process_status = ANY($1::text[])"
    if include_null:
        status_clause = f"({status_clause} OR ecd.financials_process_status IS NULL)"
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    return f"""
SELECT e.external_id, e.custom_id, e.tenant_id, e.pd_last_known_date, e.as_of_date,
       e.entity_data ->> 'financialStmtDate' AS financial_stmt_date,
       ecd.financials_process_status, ecd.financials_process_status_date,
       ecd.financials_process_id, ecd.financials_type
FROM entity e
INNER JOIN entity_custom_data ecd ON e.external_id = ecd.external_id
WHERE e.data_type = 'Private'
  AND {custom_clause}
  AND e.external_id IS NOT NULL
  AND {tenant_clause}
  AND {status_clause}
ORDER BY ecd.financials_process_status_date NULLS FIRST, e.external_id
{limit_clause}
"""


async def fetch_stuck_rows(
    *,
    mode: "rf.EntityRefreshMode",
    tenant_id: str | None,
    excluded: list[str],
    statuses: list[str],
    include_null: bool,
    limit: int | None,
) -> list[dict]:
    query = build_query(mode, tenant_id=tenant_id, include_null=include_null, limit=limit)
    status_param = statuses
    tenant_param = tenant_id if tenant_id else excluded
    conn = await rf.pg_connect()
    try:
        rows = await conn.fetch(query, status_param, tenant_param)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def fetch_current_status(external_ids: list[str]) -> dict[str, dict]:
    """Current financials status for a set of external_ids (for --recheck-from)."""
    q = """
    SELECT external_id, financials_process_status, financials_process_status_date, financials_process_id
    FROM entity_custom_data WHERE external_id = ANY($1::text[])
    """
    conn = await rf.pg_connect()
    try:
        rows = await conn.fetch(q, external_ids)
        return {r["external_id"]: dict(r) for r in rows}
    finally:
        await conn.close()


def _days_in_state(status_date, now: datetime) -> int | None:
    if status_date is None:
        return None
    if isinstance(status_date, datetime):
        sd = status_date if status_date.tzinfo else status_date.replace(tzinfo=timezone.utc)
        return (now - sd).days
    return None


def write_reports(rows: list[dict], *, out_csv: Path, tenant_csv: Path, now: datetime) -> dict:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    bucket_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    tenants: dict[str, dict] = {}

    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for rec in rows:
            days = _days_in_state(rec["financials_process_status_date"], now)
            bucket = age_bucket(days)
            status = rec["financials_process_status"] or "NULL"
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
            status_counts[status] = status_counts.get(status, 0) + 1
            writer.writerow({
                "external_id": rec["external_id"],
                "custom_id": _iso(rec["custom_id"]),
                "tenant_id": rec["tenant_id"],
                "financials_process_status": _iso(rec["financials_process_status"]),
                "financials_process_status_date": _iso(rec["financials_process_status_date"]),
                "days_in_state": days if days is not None else "",
                "age_bucket": bucket,
                "financials_process_id": _iso(rec["financials_process_id"]),
                "financials_type": _iso(rec["financials_type"]),
                "pd_last_known_date": _iso(rec["pd_last_known_date"]),
                "as_of_date": _iso(rec["as_of_date"]),
                "financial_stmt_date": _iso(rec["financial_stmt_date"]),
            })

            t = tenants.setdefault(rec["tenant_id"], {
                "tenant_id": rec["tenant_id"], "total": 0, "failed": 0, "aborted": 0,
                "started": 0, "completed_with_errors": 0, "null_status": 0,
                "chronic_gt_180d": 0, "_oldest": None,
            })
            t["total"] += 1
            key = {
                "Failed": "failed", "Aborted": "aborted", "Started": "started",
                "Completed with errors": "completed_with_errors",
            }.get(rec["financials_process_status"], "null_status")
            t[key] += 1
            if days is not None and days >= 180:
                t["chronic_gt_180d"] += 1
            sd = rec["financials_process_status_date"]
            if sd is not None and (t["_oldest"] is None or sd < t["_oldest"]):
                t["_oldest"] = sd

    with tenant_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=TENANT_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for t in sorted(tenants.values(), key=lambda x: -x["total"]):
            oldest = t.pop("_oldest")
            t["oldest_status_date"] = _iso(oldest)
            writer.writerow(t)

    return {"bucket_counts": bucket_counts, "status_counts": status_counts, "tenants": len(tenants)}


def submit_reposts(external_ids: list[str], *, mode, base_url, token_manager, workers, max_retries,
                   checkpoint: set[str], checkpoint_path: Path, logger) -> tuple[int, int]:
    todo = [e for e in external_ids if e not in checkpoint]
    logger.info("Reposting %s entities (%s already done, skipped)", len(todo), len(external_ids) - len(todo))
    total = len(todo)
    ok = fail = 0

    def one(i_ext):
        i, ext = i_ext
        return ext, rf.submit_refresh_batch(
            session=None, token_manager=token_manager, base_url=base_url, payload_type=mode.payload_type,
            entities=[ext], batch_num=i, total_batches=total, logger=logger, dry_run=False,
            verbose=False, max_retries=max_retries,
        )

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, (i, e)) for i, e in enumerate(todo, 1)]
        for f in as_completed(futs):
            ext, res = f.result()
            _, okf, _status, _ = res
            done += 1
            if okf:
                ok += 1
                with checkpoint_path.open("a", encoding="utf-8") as fh:
                    fh.write(ext + "\n")
            else:
                fail += 1
            if done % 50 == 0 or done == total:
                logger.info("Repost progress %s/%s ok=%s fail=%s", done, total, ok, fail)
    return ok, fail


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--entity-type", default="custom", help="'custom' or 'private' (default custom).")
    p.add_argument("--statuses", default=",".join(DEFAULT_TARGET_STATUSES),
                   help=f"Comma-separated financials_process_status values to target (default: {', '.join(DEFAULT_TARGET_STATUSES)}).")
    p.add_argument("--include-null-status", action="store_true",
                   help="Also include entities with NULL financials_process_status (avoid for private: ~10M).")
    p.add_argument("--tenant-id", default=None, help="Restrict to one tenant_id.")
    p.add_argument("--limit", type=int, default=None, help="Cap entities (testing).")
    p.add_argument("--submit", action="store_true", help="Re-post the target entities (WRITE). Default is report-only.")
    p.add_argument("--workers", type=int, default=8, help="Repost workers (default 8).")
    p.add_argument("--checkpoint", default=None, help="Checkpoint file of reposted external_ids (resume).")
    p.add_argument("--recheck-from", type=Path, default=None, help="Snapshot JSON to re-check status transitions.")
    p.add_argument("--output", type=Path, default=None, help="Per-entity CSV path (default under output/stale_entities/).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_started = datetime.now(timezone.utc)
    log_path = rf.logs_dir() / f"reprocess_stuck_financials_{run_started.strftime('%Y%m%d_%H%M%S')}.log"
    logger = rf.setup_logging(log_path)

    missing = rf.missing_postgres_env()
    if missing:
        logger.error("Missing Postgres settings in .env: %s", ", ".join(missing))
        return 1

    # Re-check mode.
    if args.recheck_from:
        snap = json.loads(args.recheck_from.read_text(encoding="utf-8"))
        before = snap["entities"]  # {external_id: status}
        ext_ids = list(before.keys())
        current = asyncio.run(fetch_current_status(ext_ids))
        moved = still = gone = 0
        for ext, old_status in before.items():
            cur = current.get(ext)
            if cur is None:
                gone += 1
                continue
            new_status = cur["financials_process_status"]
            if new_status in ("Completed", "Completed with errors") and old_status not in ("Completed", "Completed with errors"):
                moved += 1
            elif new_status == old_status:
                still += 1
        print("\n" + "=" * 60)
        print("RECHECK — financials status transitions since repost")
        print("=" * 60)
        print(f"  entities            : {len(ext_ids):,}")
        print(f"  -> Completed(+errs) : {moved:,}  (retry worked)")
        print(f"  still same status   : {still:,}  (chronic / not yet processed)")
        print(f"  no longer present   : {gone:,}")
        print("=" * 60 + "\n")
        return 0

    mode = rf.resolve_entity_mode(args.entity_type)
    statuses = [s.strip() for s in args.statuses.split(",") if s.strip()]
    excluded = rf.excluded_tenant_ids()
    tenant_id = (args.tenant_id or "").strip() or None
    base_url = rf.tessera_base_url()

    logger.info("Entity type: %s | statuses: %s | include_null: %s | submit: %s",
                mode.name, statuses, args.include_null_status, args.submit)

    rows = asyncio.run(fetch_stuck_rows(
        mode=mode, tenant_id=tenant_id, excluded=excluded, statuses=statuses,
        include_null=args.include_null_status, limit=args.limit,
    ))
    logger.info("Stuck entities found: %s", len(rows))
    if not rows:
        print(f"\nNo non-Completed {mode.name} financials found for {statuses}.\n")
        return 0

    ts = run_started.strftime("%Y%m%d_%H%M%S")
    if args.output is None:
        out_csv = output_dir("stale_entities") / f"stuck_financials_{mode.name}_{ts}.csv"
    else:
        out_csv = resolve_cli_artifact(args.output, "stale_entities")
    tenant_csv = out_csv.with_name(out_csv.name.replace("stuck_financials_", "stuck_financials_by_tenant_"))

    stats = write_reports(rows, out_csv=out_csv, tenant_csv=tenant_csv, now=run_started)

    # Submit (repost) if requested.
    repost_ok = repost_fail = 0
    snapshot_path = None
    if args.submit:
        # Snapshot before-status so a later --recheck-from can measure transitions.
        snapshot_path = log_path.with_suffix(".snapshot.json")
        snapshot_path.write_text(json.dumps({
            "entity_type": mode.name,
            "statuses": statuses,
            "entities": {r["external_id"]: r["financials_process_status"] for r in rows},
        }, indent=2, default=str), encoding="utf-8")

        checkpoint_path = Path(args.checkpoint) if args.checkpoint else (
            rf.logs_dir() / f"reprocess_stuck_financials_{mode.name}_checkpoint.txt")
        checkpoint = set()
        if checkpoint_path.exists():
            checkpoint = {l.strip() for l in checkpoint_path.read_text(encoding="utf-8").splitlines() if l.strip()}

        token_manager = rf.TokenManager(
            sso_url=rf._env("MOODYS_SSO_URL", rf.DEFAULT_SSO_URL), username=rf._env("MOODYS_SSO_USERNAME"),
            password=rf._env("MOODYS_SSO_PASSWORD"), max_age_seconds=rf.TOKEN_MAX_AGE_SECONDS,
            logger=logger, manual_token=rf._env("STALE_REFRESH_MANUAL_TOKEN") or None)
        try:
            token_manager.get_token()
        except Exception as exc:
            logger.error("Authentication failed: %s", exc)
            return 1
        repost_ok, repost_fail = submit_reposts(
            [r["external_id"] for r in rows], mode=mode, base_url=base_url, token_manager=token_manager,
            workers=max(1, args.workers), max_retries=rf.DEFAULT_MAX_RETRIES,
            checkpoint=checkpoint, checkpoint_path=checkpoint_path, logger=logger)

    summary = {
        "entity_type": mode.name,
        "statuses": statuses,
        "include_null_status": args.include_null_status,
        "total_stuck": len(rows),
        "by_status": stats["status_counts"],
        "by_age_bucket": stats["bucket_counts"],
        "tenants": stats["tenants"],
        "submitted": args.submit,
        "repost_ok": repost_ok,
        "repost_fail": repost_fail,
        "snapshot": str(snapshot_path) if snapshot_path else None,
        "output_csv": str(out_csv),
        "tenant_csv": str(tenant_csv),
    }
    logger.info("Run summary: %s", json.dumps(summary, indent=2, default=str))
    log_path.with_suffix(".summary.json").write_text(json.dumps({"summary": summary}, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 64)
    print(f"STUCK FINANCIALS ({mode.name}) — {'REPOSTED' if args.submit else 'REPORT ONLY'}")
    print("=" * 64)
    print(f"  Total non-Completed : {len(rows):,}")
    for s, c in sorted(stats["status_counts"].items(), key=lambda kv: -kv[1]):
        print(f"    {s:24}: {c:,}")
    print("  Age in state:")
    for b in (">180d", "90-180d", "30-90d", "<30d", "unknown"):
        if b in stats["bucket_counts"]:
            print(f"    {b:24}: {stats['bucket_counts'][b]:,}")
    if args.submit:
        print(f"  Reposted            : ok={repost_ok:,} fail={repost_fail:,}")
        print(f"  Snapshot            : {snapshot_path}")
    print(f"  Tenants affected    : {stats['tenants']:,}")
    print(f"  CSV                  : {out_csv}")
    print(f"  Tenant CSV           : {tenant_csv}")
    print("=" * 64 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
