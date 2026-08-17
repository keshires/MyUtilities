"""
Monitor entity_refresh_status for failed entities and optionally resubmit for refresh.

Read-only by default — queries entity_refresh_status for entities matching --status
(default: failed) and --source (default: Scoring), LEFT-JOINs public.entity to resolve
the entity type, and exports results to CSV.

With --resubmit, posts the failed entities directly to refreshEntities (Tessera),
bypassing the stale-date filter. These entities already passed that check once;
they failed in the downstream SQS consumer (EntityRefreshService). Entities not
found in public.entity (data_type='Private') are skipped and logged.

Resubmit groups by resolved type:
  custom_id IS NOT NULL  ->  payload 'non-public-customized'
  custom_id IS NULL      ->  payload 'non-public'
  not in public.entity   ->  skipped (logged)

Examples:
  # Report only — see what failed this month
  python monitor_entity_refresh_status.py --source Scoring --since 2026-08-01

  # Resubmit failures (dry-run first)
  python monitor_entity_refresh_status.py --source Scoring --since 2026-08-01 --resubmit --dry-run

  # Resubmit failures (live)
  python monitor_entity_refresh_status.py --source Scoring --since 2026-08-01 --resubmit --workers 3

  # Filter to a specific refresh batch
  python monitor_entity_refresh_status.py --correlation-id 69bee1c9-bc06-5436-82ab-76d761b6821c --resubmit
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

import refresh_stale_non_public_entities as rf
from project_paths import logs_dir, output_dir, resolve_cli_artifact

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

POSTGRES_ENV_KEYS = (
    "TESSERA_POSTGRES_HOST",
    "TESSERA_POSTGRES_DB",
    "TESSERA_POSTGRES_USER",
    "TESSERA_POSTGRES_PASSWORD",
)

DEFAULT_SOURCES = ["Scoring"]
DEFAULT_STATUSES = ["failed"]
DEFAULT_WORKERS = rf.DEFAULT_WORKERS
DEFAULT_MAX_RETRIES = rf.DEFAULT_MAX_RETRIES
DEFAULT_BATCH_SIZE = 500

ENTITY_NOT_FOUND = "not_found"
ENTITY_CUSTOM = "custom"
ENTITY_PRIVATE = "private"

PAYLOAD_TYPE = {
    ENTITY_CUSTOM: "non-public-customized",
    ENTITY_PRIVATE: "non-public",
}

CSV_FIELDNAMES = [
    "external_id",
    "source",
    "status",
    "failure_stage",
    "retry_count",
    "failed_at",
    "file_correlation_id",
    "created_at",
    "entity_type_resolved",
    "action",
]


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def missing_postgres_env() -> list[str]:
    return [key for key in POSTGRES_ENV_KEYS if not _env(key)]


def setup_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("monitor_entity_refresh_status")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)
    return logger


async def pg_connect() -> asyncpg.Connection:
    return await asyncpg.connect(
        host=os.environ["TESSERA_POSTGRES_HOST"],
        port=int(os.getenv("TESSERA_POSTGRES_PORT", "5432")),
        database=os.environ["TESSERA_POSTGRES_DB"],
        user=os.environ["TESSERA_POSTGRES_USER"],
        password=os.environ["TESSERA_POSTGRES_PASSWORD"],
        ssl="prefer",
    )


def build_query(
    statuses: list[str],
    sources: list[str],
    *,
    correlation_id: str | None,
    since: date | None,
) -> tuple[str, list]:
    """Build the entity_refresh_status monitoring query; return (sql, params).

    DISTINCT ON (external_id) picks the most recent row per entity.
    LEFT JOIN public.entity (data_type='Private') to resolve entity type.
    entity_found distinguishes 'not in entity table' from 'private (custom_id IS NULL)'.
    """
    where_parts = [
        "ers.status = ANY($1::text[])",
        "ers.source = ANY($2::text[])",
    ]
    params: list = [statuses, sources]
    idx = 3

    if correlation_id:
        where_parts.append(f"ers.file_correlation_id = ${idx}")
        params.append(correlation_id)
        idx += 1

    if since:
        where_parts.append(f"ers.created_at >= ${idx}")
        params.append(datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc))
        idx += 1

    where = "\n  AND ".join(where_parts)
    sql = f"""
SELECT DISTINCT ON (ers.external_id)
    ers.external_id,
    ers.source,
    ers.status,
    ers.failure_stage,
    ers.retry_count,
    ers.failed_at,
    ers.file_correlation_id,
    ers.created_at,
    (e.external_id IS NOT NULL) AS entity_found,
    e.custom_id
FROM public.entity_refresh_status ers
LEFT JOIN public.entity e
       ON e.external_id = ers.external_id
      AND e.data_type = 'Private'
WHERE {where}
ORDER BY ers.external_id, ers.created_at DESC
"""
    return sql, params


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def resolve_entity_type(entity_found: bool, custom_id: object) -> str:
    if not entity_found:
        return ENTITY_NOT_FOUND
    return ENTITY_CUSTOM if custom_id is not None else ENTITY_PRIVATE


async def fetch_failed_entities(
    statuses: list[str],
    sources: list[str],
    *,
    correlation_id: str | None,
    since: date | None,
    limit: int | None,
    logger: logging.Logger,
) -> list[dict]:
    sql, params = build_query(statuses, sources, correlation_id=correlation_id, since=since)
    logger.info("SQL query:\n%s\nparams: %s", sql, [str(p) for p in params])

    conn = await pg_connect()
    try:
        rows = await conn.fetch(sql, *params)
    finally:
        await conn.close()

    results = []
    for row in rows:
        entity_type = resolve_entity_type(bool(row["entity_found"]), row["custom_id"])
        results.append({
            "external_id": row["external_id"],
            "source": row["source"],
            "status": row["status"],
            "failure_stage": row["failure_stage"],
            "retry_count": row["retry_count"],
            "failed_at": row["failed_at"],
            "file_correlation_id": row["file_correlation_id"],
            "created_at": row["created_at"],
            "entity_type_resolved": entity_type,
        })
        if limit is not None and len(results) >= limit:
            logger.info("Reached --limit %s; stopping fetch", limit)
            break

    return results


def write_csv(
    rows: list[dict],
    *,
    action: str,
    out_csv: Path,
    logger: logging.Logger,
) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            row_action = (
                "skipped_entity_not_found"
                if row["entity_type_resolved"] == ENTITY_NOT_FOUND
                else action
            )
            writer.writerow({
                "external_id": row["external_id"],
                "source": _cell(row["source"]),
                "status": _cell(row["status"]),
                "failure_stage": _cell(row["failure_stage"]),
                "retry_count": _cell(row["retry_count"]),
                "failed_at": _cell(row["failed_at"]),
                "file_correlation_id": _cell(row["file_correlation_id"]),
                "created_at": _cell(row["created_at"]),
                "entity_type_resolved": row["entity_type_resolved"],
                "action": row_action,
            })
    logger.info("CSV written: %s (%s rows)", out_csv, len(rows))


def submit_group(
    entities: list[str],
    *,
    payload_type: str,
    entity_type_label: str,
    token_manager: rf.TokenManager,
    base_url: str,
    batch_size: int,
    workers: int,
    dry_run: bool,
    max_retries: int,
    logger: logging.Logger,
) -> tuple[int, int, list[dict]]:
    """Submit one entity-type group to refreshEntities. Returns (ok_batches, fail_batches, failed_details)."""
    batches = [entities[i : i + batch_size] for i in range(0, len(entities), batch_size)]
    total_batches = len(batches)
    logger.info(
        "Submitting %s %s entities in %s batch(es) (payload_type=%s)",
        len(entities),
        entity_type_label,
        total_batches,
        payload_type,
    )

    ok_count = 0
    fail_count = 0
    failed_batches: list[dict] = []
    session = rf.create_http_session(workers) if workers == 1 else None

    if workers <= 1:
        for batch_num, batch in enumerate(batches, start=1):
            _, ok, status_code, detail = rf.submit_refresh_batch(
                session=session,
                token_manager=token_manager,
                base_url=base_url,
                payload_type=payload_type,
                entities=batch,
                batch_num=batch_num,
                total_batches=total_batches,
                logger=logger,
                dry_run=dry_run,
                verbose=True,
                max_retries=max_retries,
            )
            if ok:
                ok_count += 1
            else:
                fail_count += 1
                failed_batches.append({
                    "batch": batch_num,
                    "entity_count": len(batch),
                    "success": False,
                    "http_status": status_code,
                    "detail": detail,
                })
    else:
        futures = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for batch_num, batch in enumerate(batches, start=1):
                if not dry_run and token_manager._is_expired():
                    token_manager.get_token(force_refresh=True)
                fut = executor.submit(
                    rf.submit_refresh_batch,
                    session=None,
                    token_manager=token_manager,
                    base_url=base_url,
                    payload_type=payload_type,
                    entities=batch,
                    batch_num=batch_num,
                    total_batches=total_batches,
                    logger=logger,
                    dry_run=dry_run,
                    verbose=False,
                    max_retries=max_retries,
                )
                futures[fut] = (batch_num, len(batch))

            for future in as_completed(futures):
                batch_num, entity_count = futures[future]
                _, ok, status_code, detail = future.result()
                if ok:
                    ok_count += 1
                else:
                    fail_count += 1
                    failed_batches.append({
                        "batch": batch_num,
                        "entity_count": entity_count,
                        "success": False,
                        "http_status": status_code,
                        "detail": detail,
                    })

    return ok_count, fail_count, failed_batches


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        default=",".join(DEFAULT_SOURCES),
        help=(
            "Comma-separated source(s) to filter on (default: %(default)s). "
            "Example: Scoring,Pipeline"
        ),
    )
    parser.add_argument(
        "--status",
        default=",".join(DEFAULT_STATUSES),
        help="Comma-separated status value(s) to filter on (default: %(default)s).",
    )
    parser.add_argument(
        "--correlation-id",
        default=None,
        help="Filter by file_correlation_id (optional).",
    )
    parser.add_argument(
        "--since",
        default=None,
        help=(
            "Include only records with created_at >= YYYY-MM-DD (optional; "
            "recommended — scopes to the partition and avoids a full table scan)."
        ),
    )
    parser.add_argument(
        "--resubmit",
        action="store_true",
        help="Post matched entities to refreshEntities. Default: report only.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --resubmit: log what would be posted without calling the API.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Parallel API workers when --resubmit is set (default: {DEFAULT_WORKERS}).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Entities per refreshEntities call when --resubmit is set (default: {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Retry attempts per batch on transient errors (default: {DEFAULT_MAX_RETRIES}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap matched entities for testing.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="CSV output path (default: output/monitor_entity_refresh_status/ers_<utc>.csv).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sources = [s.strip() for s in args.source.split(",") if s.strip()]
    statuses = [s.strip() for s in args.status.split(",") if s.strip()]
    correlation_id = (args.correlation_id or "").strip() or None

    since: date | None = None
    if args.since:
        try:
            since = datetime.strptime(args.since, "%Y-%m-%d").date()
        except ValueError:
            raise SystemExit(f"--since must be YYYY-MM-DD, got: {args.since!r}")

    run_started = datetime.now(timezone.utc)
    log_path = (
        logs_dir("monitor_entity_refresh_status")
        / f"monitor_entity_refresh_status_{run_started.strftime('%Y%m%d_%H%M%S')}.log"
    )
    logger = setup_logging(log_path)

    missing = missing_postgres_env()
    if missing:
        logger.error("Missing Postgres settings in .env: %s", ", ".join(missing))
        return 1

    if args.output is None:
        ts = run_started.strftime("%Y%m%d_%H%M%S")
        out_csv = output_dir("monitor_entity_refresh_status") / f"ers_{ts}.csv"
    else:
        out_csv = resolve_cli_artifact(args.output, "monitor_entity_refresh_status")

    logger.info("Run started")
    logger.info("Sources: %s", sources)
    logger.info("Statuses: %s", statuses)
    if correlation_id:
        logger.info("Correlation ID filter: %s", correlation_id)
    if since:
        logger.info("Since (created_at >=): %s", since.isoformat())
    logger.info(
        "Mode: %s",
        "resubmit" + (" (dry-run)" if args.dry_run else "") if args.resubmit else "report-only",
    )
    logger.info("Log file: %s", log_path)
    logger.info("Output CSV: %s", out_csv)

    try:
        rows = asyncio.run(
            fetch_failed_entities(
                statuses,
                sources,
                correlation_id=correlation_id,
                since=since,
                limit=args.limit,
                logger=logger,
            )
        )
    except Exception as exc:
        logger.exception("DB query failed: %s", exc)
        return 1

    by_type: dict[str, list[str]] = {
        ENTITY_CUSTOM: [],
        ENTITY_PRIVATE: [],
        ENTITY_NOT_FOUND: [],
    }
    for row in rows:
        by_type[row["entity_type_resolved"]].append(row["external_id"])

    logger.info(
        "Matched %s entity(ies): custom=%s private=%s not_found=%s",
        len(rows),
        len(by_type[ENTITY_CUSTOM]),
        len(by_type[ENTITY_PRIVATE]),
        len(by_type[ENTITY_NOT_FOUND]),
    )
    if by_type[ENTITY_NOT_FOUND]:
        logger.warning(
            "Skipped %s external_id(s) not found in public.entity (data_type='Private'): %s%s",
            len(by_type[ENTITY_NOT_FOUND]),
            by_type[ENTITY_NOT_FOUND][:10],
            " ..." if len(by_type[ENTITY_NOT_FOUND]) > 10 else "",
        )

    action = "report_only"
    resubmit_summary: dict[str, object] = {}

    if args.resubmit:
        action = "dry_run" if args.dry_run else "resubmitted"
        base_url = rf.tessera_base_url()
        batch_size = max(1, args.batch_size)
        workers = max(1, args.workers)
        max_retries = max(0, args.max_retries)

        token_manager = rf.TokenManager(
            sso_url=_env("MOODYS_SSO_URL", rf.DEFAULT_SSO_URL),
            username=_env("MOODYS_SSO_USERNAME"),
            password=_env("MOODYS_SSO_PASSWORD"),
            max_age_seconds=rf.TOKEN_MAX_AGE_SECONDS,
            logger=logger,
            manual_token=_env("STALE_REFRESH_MANUAL_TOKEN") or None,
        )
        if not args.dry_run:
            try:
                token_manager.get_token()
            except Exception as exc:
                logger.error("Authentication failed: %s", exc)
                return 1

        total_ok = 0
        total_fail = 0
        all_failed_batches: list[dict] = []

        for entity_type, payload_type in PAYLOAD_TYPE.items():
            ids = by_type[entity_type]
            if not ids:
                continue
            ok, fail, failed_batches = submit_group(
                ids,
                payload_type=payload_type,
                entity_type_label=entity_type,
                token_manager=token_manager,
                base_url=base_url,
                batch_size=batch_size,
                workers=workers,
                dry_run=args.dry_run,
                max_retries=max_retries,
                logger=logger,
            )
            total_ok += ok
            total_fail += fail
            all_failed_batches.extend(failed_batches)

        resubmit_summary = {
            "batches_ok": total_ok,
            "batches_failed": total_fail,
            "failed_batches": all_failed_batches,
        }
        logger.info(
            "Resubmit complete — batches ok=%s failed=%s",
            total_ok,
            total_fail,
        )

    write_csv(rows, action=action, out_csv=out_csv, logger=logger)

    elapsed = (datetime.now(timezone.utc) - run_started).total_seconds()
    summary = {
        "run_started": run_started.isoformat(),
        "sources": sources,
        "statuses": statuses,
        "correlation_id": correlation_id,
        "since": since.isoformat() if since else None,
        "limit": args.limit,
        "mode": action,
        "matched": len(rows),
        "by_entity_type": {
            ENTITY_CUSTOM: len(by_type[ENTITY_CUSTOM]),
            ENTITY_PRIVATE: len(by_type[ENTITY_PRIVATE]),
            ENTITY_NOT_FOUND: len(by_type[ENTITY_NOT_FOUND]),
        },
        **resubmit_summary,
        "output_csv": str(out_csv),
        "elapsed_seconds": round(elapsed, 2),
    }
    logger.info("Run summary: %s", json.dumps(summary, indent=2))

    summary_path = log_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps({"summary": summary}, indent=2), encoding="utf-8")
    logger.info("Summary JSON: %s", summary_path)

    if not rows:
        print(f"\nNo entities matched (status={statuses}, source={sources}).\n")
    else:
        print(f"\nMatched {len(rows)} entity(ies) — CSV: {out_csv}\n")
        print(
            f"  custom={len(by_type[ENTITY_CUSTOM])}  "
            f"private={len(by_type[ENTITY_PRIVATE])}  "
            f"not_found={len(by_type[ENTITY_NOT_FOUND])}"
        )
        if args.resubmit:
            print(
                f"  Resubmit batches — ok={resubmit_summary.get('batches_ok', 0)} "
                f"failed={resubmit_summary.get('batches_failed', 0)}"
            )
    print()

    had_error = int(resubmit_summary.get("batches_failed", 0)) > 0
    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
