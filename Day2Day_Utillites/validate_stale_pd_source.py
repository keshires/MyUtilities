"""
Validate the *left-over* stale entities against the EDFX PDs API to prove whether
each entity's ``pd_last_known_date`` is already dated to the maximum the source
data supports — or whether it is genuinely behind and worth refreshing.

For every still-stale entity (same predicates as
``refresh_stale_non_public_entities.py``: recent financials, ``pd_last_known_date``
before the cutoff, excluded tenants) we:

  1. Read ``financials_process_id`` from ``entity_custom_data`` (1:1 with entity).
  2. Build ``entityId = {external_id}-{financials_process_id}``.
  3. POST batches to ``/edfx/v1/entities/pds`` (asyncResponse=false) and read the
     latest ``asOfDate`` the model can produce.
  4. Compare API ``asOfDate`` with the DB ``pd_last_known_date`` and assign a
     verdict, then write everything to CSV.

Entities with a NULL ``financials_process_id`` are submitted for refresh (so they
get a new process id) and flagged in the CSV — no API call is possible for them.

Read-only against the DB. Calls the PDs API (read) and, for NULL-process-id rows,
the refreshEntities API (write) unless ``--dry-run``.

Examples:
  python validate_stale_pd_source.py --entity-type custom
  python validate_stale_pd_source.py --entity-type custom --limit 100
  python validate_stale_pd_source.py --entity-type custom --api-batch-size 100 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests

import refresh_stale_non_public_entities as rf
from project_paths import output_dir, resolve_cli_artifact

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PDS_ENDPOINT = "/edfx/v1/entities/pds"
DEFAULT_API_BATCH_SIZE = 50
DEFAULT_API_PAUSE_SECONDS = 0.25  # brief gap between calls so we don't overload the API

CSV_FIELDS = [
    "external_id",
    "custom_id",
    "tenant_id",
    "financials_process_status",
    "financials_process_id",
    "entity_id",
    "financial_stmt_date",
    "db_pd_last_known_date",
    "db_as_of_date",
    "db_updated_date",
    "api_as_of_date",
    "api_pd",
    "api_implied_rating",
    "api_confidence",
    "api_confidence_description",
    "verdict",
]


def _pd_stale_where(stale_date_column: str, financial_max_age_years: int) -> str:
    """WHERE fragments (e.-prefixed, so they're unambiguous across the join)."""
    fin = ""
    if financial_max_age_years > 0:
        fin = (
            "AND (\n"
            "        NULLIF(e.entity_data ->> 'financialStmtDate', '') IS NULL\n"
            "        OR NULLIF(e.entity_data ->> 'financialStmtDate', '')::timestamp"
            f" >= (NOW() - INTERVAL '{financial_max_age_years} years')\n"
            "      )"
        )
    stale = (
        f"AND (e.{stale_date_column} IS NULL OR e.{stale_date_column} < $1::timestamp)"
    )
    return f"{fin}\n  {stale}"


def build_query(
    mode: "rf.EntityRefreshMode",
    *,
    stale_date_column: str,
    financial_max_age_years: int,
    tenant_id: str | None,
    limit: int | None,
) -> str:
    tenant_clause = "e.tenant_id = $2::text" if tenant_id else "e.tenant_id <> ALL($2::text[])"
    where = _pd_stale_where(stale_date_column, financial_max_age_years)
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    custom_clause = mode.custom_id_clause.replace("custom_id", "e.custom_id")
    return f"""
SELECT e.external_id, e.custom_id, e.tenant_id, e.pd_last_known_date, e.as_of_date,
       e.updated_date AS e_updated_date,
       e.entity_data ->> 'financialStmtDate' AS financial_stmt_date,
       ecd.financials_process_id, ecd.transit_financials_process_id,
       ecd.financials_process_status
FROM entity e
INNER JOIN entity_custom_data ecd ON e.external_id = ecd.external_id
WHERE e.data_type = 'Private'
  AND {custom_clause}
  AND e.external_id IS NOT NULL
  AND {tenant_clause}
  {where}
ORDER BY e.external_id
{limit_clause}
"""


def _iso(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _as_date(value: object) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


async def fetch_stale_rows(
    *,
    mode: "rf.EntityRefreshMode",
    stale_date_column: str,
    financial_max_age_years: int,
    tenant_id: str | None,
    excluded: list[str],
    cutoff: datetime,
    limit: int | None,
) -> list[dict]:
    query = build_query(
        mode,
        stale_date_column=stale_date_column,
        financial_max_age_years=financial_max_age_years,
        tenant_id=tenant_id,
        limit=limit,
    )
    tenant_param = tenant_id if tenant_id else excluded
    conn = await rf.pg_connect()
    try:
        rows = await conn.fetch(query, cutoff, tenant_param)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


def fetch_pds_batch(
    entity_ids: list[str],
    *,
    token_manager: "rf.TokenManager",
    base_url: str,
    logger,
    max_retries: int,
) -> dict[str, dict]:
    """POST a batch to the PDs endpoint; return {entityId: result}. Retries 5xx /
    network errors with backoff. Raises on unrecoverable failure."""
    url = f"{base_url}{PDS_ENDPOINT}"
    payload = {
        "asyncResponse": False,
        "modelParameters": {
            "fso": False,
            "modelId": None,
            "disableRelativeContribution": None,
            "version": None,
        },
        "includeDetail": {
            "resultDetail": False,
            "inputDetail": False,
            "modelDetail": False,
            "includeTermStructure": False,
            "includeHistoryTermStructure": False,
        },
        "entities": [{"entityId": eid} for eid in entity_ids],
    }
    retries_used = 0
    while True:
        token = token_manager.get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            resp = requests.post(
                url, headers=headers, json=payload, verify=False, timeout=rf.REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            if retries_used < max_retries:
                retries_used += 1
                delay = rf.retry_backoff_seconds(retries_used)
                logger.warning("PDs request error (%s) — retry %s/%s in %.1fs", exc, retries_used, max_retries, delay)
                time.sleep(delay)
                continue
            raise

        if resp.status_code == 401 and retries_used == 0:
            token_manager.invalidate()
            retries_used += 0  # 401 handled once, not counted as a backoff retry
            token_manager.get_token(force_refresh=True)
            continue
        if resp.status_code in rf.RETRYABLE_STATUS_CODES and retries_used < max_retries:
            retries_used += 1
            delay = rf.retry_backoff_seconds(retries_used)
            logger.warning("PDs HTTP %s — retry %s/%s in %.1fs", resp.status_code, retries_used, max_retries, delay)
            time.sleep(delay)
            continue
        resp.raise_for_status()
        data = resp.json()
        return {e.get("entityId"): e for e in data.get("entities", [])}


def verdict_for(db_pd: date | None, api_as_of: date | None, *, has_api: bool) -> str:
    if not has_api or api_as_of is None:
        return "no_api_data"
    if db_pd is None:
        return "db_behind_api"  # DB had no PD, API produced one
    if api_as_of > db_pd:
        return "db_behind_api"
    if api_as_of < db_pd:
        return "db_ahead_api"
    return "at_source_max"


def build_row(rec: dict, entity_id: str | None, api: dict | None) -> dict:
    db_pd = _as_date(rec["pd_last_known_date"])
    api_as_of = _as_date(api.get("asOfDate")) if api else None
    if entity_id is None:
        verdict = "no_process_id_refresh_submitted"
    else:
        verdict = verdict_for(db_pd, api_as_of, has_api=api is not None)
    return {
        "external_id": rec["external_id"],
        "custom_id": _iso(rec["custom_id"]),
        "tenant_id": rec["tenant_id"],
        "financials_process_status": _iso(rec["financials_process_status"]),
        "financials_process_id": _iso(rec["financials_process_id"]),
        "entity_id": entity_id or "",
        "financial_stmt_date": _iso(rec["financial_stmt_date"]),
        "db_pd_last_known_date": _iso(rec["pd_last_known_date"]),
        "db_as_of_date": _iso(rec["as_of_date"]),
        "db_updated_date": _iso(rec["e_updated_date"]),
        "api_as_of_date": _iso(api.get("asOfDate")) if api else "",
        "api_pd": _iso(api.get("pd")) if api else "",
        "api_implied_rating": _iso(api.get("impliedRating")) if api else "",
        "api_confidence": _iso(api.get("confidence")) if api else "",
        "api_confidence_description": _iso(api.get("confidenceDescription")) if api else "",
        "verdict": verdict,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--entity-type", default="custom", help="'custom' or 'private' (default custom).")
    p.add_argument("--stale-date-column", default=None, choices=rf.STALE_DATE_COLUMNS,
                   help=f"Stale column (default {rf.DEFAULT_STALE_DATE_COLUMN}).")
    p.add_argument("--financial-max-age-years", type=int, default=rf.DEFAULT_FINANCIAL_STMT_MAX_AGE_YEARS,
                   help=f"financialStmtDate max age (default {rf.DEFAULT_FINANCIAL_STMT_MAX_AGE_YEARS}; 0 disables).")
    p.add_argument("--date-filter", default=None, help="Stale cutoff YYYY-MM-DD (default first of month).")
    p.add_argument("--tenant-id", default=None, help="Restrict to one tenant_id.")
    p.add_argument("--limit", type=int, default=None, help="Cap entities (testing).")
    p.add_argument("--api-batch-size", type=int, default=DEFAULT_API_BATCH_SIZE,
                   help=f"entityIds per PDs call (default {DEFAULT_API_BATCH_SIZE}).")
    p.add_argument("--api-pause", type=float, default=DEFAULT_API_PAUSE_SECONDS,
                   help=f"Seconds to pause between PDs calls (default {DEFAULT_API_PAUSE_SECONDS}).")
    p.add_argument("--no-refresh-missing", action="store_true",
                   help="Do NOT submit NULL-process-id entities for refresh; just flag them.")
    p.add_argument("--dry-run", action="store_true", help="No API calls (PDs or refresh); DB + CSV only.")
    p.add_argument("--output", type=Path, default=None, help="CSV path (default under output/stale_entities/).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mode = rf.resolve_entity_mode(args.entity_type)
    stale_date_column = rf.resolve_stale_date_column(
        args.stale_date_column or rf._env("STALE_REFRESH_STALE_DATE_COLUMN")
    )
    financial_max_age_years = max(0, args.financial_max_age_years)

    run_started = datetime.now(timezone.utc)
    log_path = rf.logs_dir() / f"validate_stale_pd_source_{mode.name}_{run_started.strftime('%Y%m%d_%H%M%S')}.log"
    logger = rf.setup_logging(log_path)

    missing = rf.missing_postgres_env()
    if missing:
        logger.error("Missing Postgres settings in .env: %s", ", ".join(missing))
        return 1

    cutoff_date = (
        datetime.strptime(args.date_filter, "%Y-%m-%d").date() if args.date_filter else rf.first_of_current_month()
    )
    cutoff = datetime.combine(cutoff_date, datetime.min.time())
    excluded = rf.excluded_tenant_ids()
    tenant_id = (args.tenant_id or "").strip() or None
    base_url = rf.tessera_base_url()
    api_batch_size = max(1, args.api_batch_size)
    max_retries = rf.DEFAULT_MAX_RETRIES

    if args.output is None:
        ts = run_started.strftime("%Y%m%d_%H%M%S")
        out_csv = output_dir("stale_entities") / f"stale_pd_source_{mode.name}_{ts}.csv"
    else:
        out_csv = resolve_cli_artifact(args.output, "stale_entities")

    logger.info("Entity type: %s | stale column: %s | financial max age: %s yr",
                mode.name, stale_date_column, financial_max_age_years)
    logger.info("Cutoff (%s <): %s | batch size: %s | dry_run: %s",
                stale_date_column, cutoff_date.isoformat(), api_batch_size, args.dry_run)

    rows = asyncio.run(fetch_stale_rows(
        mode=mode, stale_date_column=stale_date_column, financial_max_age_years=financial_max_age_years,
        tenant_id=tenant_id, excluded=excluded, cutoff=cutoff, limit=args.limit,
    ))
    logger.info("Fetched %s stale rows", len(rows))
    if not rows:
        print(f"\nNo stale {mode.name} entities — nothing to validate.\n")
        return 0

    # Split: entities we can query (have a financials_process_id) vs missing (NULL).
    with_pid: list[dict] = []
    missing_pid: list[dict] = []
    entity_id_to_row: dict[str, dict] = {}
    for rec in rows:
        fpid = rec["financials_process_id"]
        if fpid:
            eid = f"{rec['external_id']}-{fpid}"
            entity_id_to_row[eid] = rec
            rec["_entity_id"] = eid
            with_pid.append(rec)
        else:
            missing_pid.append(rec)
    logger.info("With process_id: %s | missing process_id: %s", len(with_pid), len(missing_pid))

    token_manager = rf.TokenManager(
        sso_url=rf._env("MOODYS_SSO_URL", rf.DEFAULT_SSO_URL),
        username=rf._env("MOODYS_SSO_USERNAME"),
        password=rf._env("MOODYS_SSO_PASSWORD"),
        max_age_seconds=rf.TOKEN_MAX_AGE_SECONDS,
        logger=logger,
        manual_token=rf._env("STALE_REFRESH_MANUAL_TOKEN") or None,
    )
    if not args.dry_run and (with_pid or (missing_pid and not args.no_refresh_missing)):
        try:
            token_manager.get_token()
        except Exception as exc:
            logger.error("Authentication failed: %s", exc)
            return 1

    # Query the PDs API in batches.
    api_by_entity: dict[str, dict] = {}
    batches = [with_pid[i:i + api_batch_size] for i in range(0, len(with_pid), api_batch_size)]
    for bi, batch in enumerate(batches, start=1):
        entity_ids = [rec["_entity_id"] for rec in batch]
        if args.dry_run:
            logger.info("[DRY RUN] PDs batch %s/%s — would query %s entityIds", bi, len(batches), len(entity_ids))
            continue
        try:
            result = fetch_pds_batch(entity_ids, token_manager=token_manager, base_url=base_url,
                                     logger=logger, max_retries=max_retries)
            api_by_entity.update(result)
        except Exception as exc:
            logger.error("PDs batch %s/%s failed: %s", bi, len(batches), exc)
        if bi % 10 == 0 or bi == len(batches):
            logger.info("PDs progress: %s/%s batches", bi, len(batches))
        if args.api_pause > 0 and bi < len(batches):
            time.sleep(args.api_pause)

    # Refresh the NULL-process-id entities so they get a new process id.
    refresh_submitted = False
    if missing_pid and not args.no_refresh_missing and not args.dry_run:
        ext_ids = [r["external_id"] for r in missing_pid]
        logger.info("Submitting %s NULL-process-id entities for refresh", len(ext_ids))
        _, ok, status, _ = rf.submit_refresh_batch(
            session=rf.create_http_session(1), token_manager=token_manager, base_url=base_url,
            payload_type=mode.payload_type, entities=ext_ids, batch_num=1, total_batches=1,
            logger=logger, dry_run=False, verbose=True, max_retries=max_retries,
        )
        refresh_submitted = ok
        logger.info("Refresh submission for missing-process-id entities: ok=%s status=%s", ok, status)

    # Build CSV rows.
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    verdict_counts: dict[str, int] = {}
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for rec in with_pid:
            api = api_by_entity.get(rec["_entity_id"])
            row = build_row(rec, rec["_entity_id"], api)
            writer.writerow(row)
            verdict_counts[row["verdict"]] = verdict_counts.get(row["verdict"], 0) + 1
        for rec in missing_pid:
            row = build_row(rec, None, None)
            writer.writerow(row)
            verdict_counts[row["verdict"]] = verdict_counts.get(row["verdict"], 0) + 1

    elapsed = (datetime.now(timezone.utc) - run_started).total_seconds()
    summary = {
        "entity_type": mode.name,
        "stale_date_column": stale_date_column,
        "financial_max_age_years": financial_max_age_years,
        "cutoff": cutoff_date.isoformat(),
        "total_rows": len(rows),
        "with_process_id": len(with_pid),
        "missing_process_id": len(missing_pid),
        "missing_refresh_submitted": refresh_submitted,
        "verdicts": verdict_counts,
        "output_csv": str(out_csv),
        "dry_run": args.dry_run,
        "elapsed_seconds": round(elapsed, 2),
    }
    logger.info("Run summary: %s", json.dumps(summary, indent=2))
    summary_path = log_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps({"summary": summary}, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print("PD SOURCE VALIDATION")
    print("=" * 60)
    print(f"  Entities checked : {len(rows):,}")
    for v, c in sorted(verdict_counts.items(), key=lambda kv: -kv[1]):
        print(f"    {v:34}: {c:,}")
    print(f"  CSV              : {out_csv}")
    print("=" * 60 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
