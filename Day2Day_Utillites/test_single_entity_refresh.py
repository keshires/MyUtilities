"""One-off experiment: submit the top N stale *custom* entities **individually**
(one entity per ``refreshEntities`` request) and check whether their
``pd_last_known_date`` advances afterwards.

Motivation: full 15,000-entity batches appear to be accepted (HTTP 200) but the
entities are not actually refreshed, whereas single-entity requests do get
processed. This script isolates the single-entity path and measures the effect.

Selection mirrors ``refresh_stale_non_public_entities.py`` (custom mode):
    data_type = 'Private' AND custom_id IS NOT NULL AND external_id IS NOT NULL
    AND tenant_id excluded  AND (pd_last_known_date IS NULL OR < cutoff)
    ORDER BY external_id LIMIT N

Flow:
    1. Snapshot the top N rows (before pd_last_known_date / updated_date).
    2. POST each external_id on its own to refreshEntities.
    3. Poll the same rows, comparing pd_last_known_date, until all advance or
       --max-wait elapses.
    4. Write a before/after JSON so you can re-check later with --recheck-from.

Usage:
    python test_single_entity_refresh.py --count 10
    python test_single_entity_refresh.py --count 10 --max-wait 600 --interval 60
    python test_single_entity_refresh.py --recheck-from output/.../<snapshot>.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import refresh_stale_non_public_entities as rf
from project_paths import output_dir

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SELECT_TOP_STALE = """
SELECT external_id, tenant_id, custom_id, pd_last_known_date, updated_date, as_of_date
FROM public.entity
WHERE data_type = 'Private'
  AND {custom_id_clause}
  AND external_id IS NOT NULL
  AND tenant_id <> ALL($2::text[])
  {financial_clause}
  AND (pd_last_known_date IS NULL OR pd_last_known_date < $1::timestamp)
ORDER BY external_id
LIMIT $3
"""

RECHECK_BY_IDS = """
SELECT external_id, tenant_id, custom_id, pd_last_known_date, updated_date, as_of_date
FROM public.entity
WHERE external_id = ANY($1::text[])
  AND data_type = 'Private'
ORDER BY external_id
"""


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _row_key(rec) -> tuple[str, str]:
    return (str(rec["external_id"]), str(rec["tenant_id"]))


def _snapshot(rec) -> dict[str, object]:
    return {
        "external_id": str(rec["external_id"]),
        "tenant_id": str(rec["tenant_id"]),
        "custom_id": _iso(rec["custom_id"]),
        "pd_last_known_date": _iso(rec["pd_last_known_date"]),
        "updated_date": _iso(rec["updated_date"]),
        "as_of_date": _iso(rec["as_of_date"]),
    }


async def fetch_top_stale(
    cutoff: datetime,
    excluded: list[str],
    count: int,
    *,
    mode: "rf.EntityRefreshMode",
    financial_max_age_years: int,
) -> list[dict]:
    query = SELECT_TOP_STALE.format(
        custom_id_clause=mode.custom_id_clause,
        financial_clause=rf.financial_stmt_clause(financial_max_age_years),
    )
    conn = await rf.pg_connect()
    try:
        rows = await conn.fetch(query, cutoff, excluded, count)
        return [_snapshot(r) for r in rows]
    finally:
        await conn.close()


async def fetch_by_ids(external_ids: list[str]) -> list[dict]:
    conn = await rf.pg_connect()
    try:
        rows = await conn.fetch(RECHECK_BY_IDS, external_ids)
        return [_snapshot(r) for r in rows]
    finally:
        await conn.close()


def _advanced(before: str | None, after: str | None) -> bool:
    """True if pd_last_known_date moved forward (incl. NULL -> value)."""
    if after is None:
        return False
    if before is None:
        return True
    return after > before


def compare(before: list[dict], after: list[dict]) -> list[dict]:
    after_by_key = {(r["external_id"], r["tenant_id"]): r for r in after}
    results = []
    for b in before:
        key = (b["external_id"], b["tenant_id"])
        a = after_by_key.get(key)
        results.append({
            "external_id": b["external_id"],
            "tenant_id": b["tenant_id"],
            "pd_before": b["pd_last_known_date"],
            "pd_after": a["pd_last_known_date"] if a else None,
            "pd_advanced": _advanced(b["pd_last_known_date"], a["pd_last_known_date"]) if a else False,
            "updated_before": b["updated_date"],
            "updated_after": a["updated_date"] if a else None,
            "updated_changed": (a and a["updated_date"] != b["updated_date"]) or False,
        })
    return results


def print_table(results: list[dict]) -> tuple[int, int]:
    advanced = sum(1 for r in results if r["pd_advanced"])
    changed = sum(1 for r in results if r["updated_changed"])
    print("\n" + "=" * 100)
    print("REFRESH VALIDATION — pd_last_known_date before/after (single-entity submissions)")
    print("=" * 100)
    for r in results:
        flag = "REFRESHED" if r["pd_advanced"] else ("updated_date moved" if r["updated_changed"] else "no change")
        print(f"  {r['external_id']:<24} pd: {str(r['pd_before']):<28} -> {str(r['pd_after']):<28} [{flag}]")
    print("-" * 100)
    print(f"  pd_last_known_date advanced : {advanced}/{len(results)}")
    print(f"  updated_date changed        : {changed}/{len(results)}")
    print("=" * 100 + "\n")
    return advanced, changed


def submit_individually(
    external_ids: list[str], *, base_url: str, token_manager, payload_type: str, max_retries: int, logger
) -> list[dict]:
    session = rf.create_http_session(1)
    outcomes = []
    total = len(external_ids)
    for i, ext_id in enumerate(external_ids, start=1):
        batch_num, ok, status, detail = rf.submit_refresh_batch(
            session=session,
            token_manager=token_manager,
            base_url=base_url,
            payload_type=payload_type,
            entities=[ext_id],
            batch_num=i,
            total_batches=total,
            logger=logger,
            dry_run=False,
            verbose=True,
            max_retries=max_retries,
        )
        outcomes.append({"external_id": ext_id, "ok": ok, "http_status": status})
        logger.info("Submitted %s/%s external_id=%s ok=%s status=%s", i, total, ext_id, ok, status)
    return outcomes


def poll_until_refreshed(
    before: list[dict], *, max_wait: int, interval: int, logger
) -> list[dict]:
    external_ids = sorted({b["external_id"] for b in before})
    deadline = time.monotonic() + max_wait
    after = before
    while True:
        after = asyncio.run(fetch_by_ids(external_ids))
        results = compare(before, after)
        advanced = sum(1 for r in results if r["pd_advanced"])
        logger.info("Re-check: %s/%s advanced (pd_last_known_date)", advanced, len(results))
        if advanced >= len(results) or time.monotonic() >= deadline:
            return results
        time.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=10, help="Number of top stale entities (default 10).")
    parser.add_argument("--entity-type", default="custom", help="'custom' or 'private' (default custom).")
    parser.add_argument("--date-filter", type=str, default=None, help="Stale cutoff (YYYY-MM-DD). Default first of month.")
    parser.add_argument(
        "--financial-max-age-years",
        type=int,
        default=rf.DEFAULT_FINANCIAL_STMT_MAX_AGE_YEARS,
        help=f"Only include entities with financialStmtDate missing or within N years (default {rf.DEFAULT_FINANCIAL_STMT_MAX_AGE_YEARS}; 0 disables).",
    )
    parser.add_argument("--max-wait", type=int, default=180, help="Seconds to poll for pd_last_known_date to advance (default 180).")
    parser.add_argument("--interval", type=int, default=30, help="Poll interval seconds (default 30).")
    parser.add_argument("--recheck-from", type=Path, default=None, help="Skip submit; just re-compare against a saved before-snapshot JSON.")
    args = parser.parse_args(argv)

    run_started = datetime.now(timezone.utc)
    log_path = rf.logs_dir("verify_single_entity_refresh") / f"test_single_entity_refresh_{run_started.strftime('%Y%m%d_%H%M%S')}.log"
    logger = rf.setup_logging(log_path)

    missing = rf.missing_postgres_env()
    if missing:
        logger.error("Missing Postgres settings in .env: %s", ", ".join(missing))
        return 1

    # Re-check mode: compare a prior snapshot against the DB now, no submissions.
    if args.recheck_from:
        before = json.loads(args.recheck_from.read_text(encoding="utf-8"))["before"]
        external_ids = sorted({b["external_id"] for b in before})
        after = asyncio.run(fetch_by_ids(external_ids))
        results = compare(before, after)
        print_table(results)
        return 0

    if args.date_filter:
        cutoff_date = datetime.strptime(args.date_filter, "%Y-%m-%d").date()
    else:
        cutoff_date = rf.first_of_current_month()
    cutoff = datetime.combine(cutoff_date, datetime.min.time())
    excluded = rf.excluded_tenant_ids()
    base_url = rf.tessera_base_url()
    mode = rf.resolve_entity_mode(args.entity_type)
    payload_type = mode.payload_type
    financial_max_age_years = max(0, args.financial_max_age_years)

    logger.info("Entity type: %s (payload type=%s)", mode.name, payload_type)
    logger.info("Cutoff (pd_last_known_date <): %s", cutoff_date.isoformat())
    logger.info(
        "Financial statement max age: %s",
        f"{financial_max_age_years} years" if financial_max_age_years > 0 else "disabled",
    )
    logger.info("Excluded tenants: %s", excluded)
    logger.info("Fetching top %s stale %s entities...", args.count, mode.name)

    before = asyncio.run(
        fetch_top_stale(
            cutoff, excluded, args.count,
            mode=mode, financial_max_age_years=financial_max_age_years,
        )
    )
    if not before:
        print(f"No stale {mode.name} entities found — nothing to test.")
        return 0

    external_ids = list(dict.fromkeys(b["external_id"] for b in before))  # dedupe, keep order
    logger.info("Selected %s external_ids: %s", len(external_ids), external_ids)

    # Auth (same as the refresh script).
    manual_token = rf._env("STALE_REFRESH_MANUAL_TOKEN") or None
    token_manager = rf.TokenManager(
        sso_url=rf._env("MOODYS_SSO_URL", rf.DEFAULT_SSO_URL),
        username=rf._env("MOODYS_SSO_USERNAME"),
        password=rf._env("MOODYS_SSO_PASSWORD"),
        max_age_seconds=rf.TOKEN_MAX_AGE_SECONDS,
        logger=logger,
        manual_token=manual_token,
    )
    try:
        token_manager.get_token()
    except Exception as exc:
        logger.error("Authentication failed: %s", exc)
        return 1

    logger.info("Submitting %s entities individually (one per request)...", len(external_ids))
    outcomes = submit_individually(
        external_ids,
        base_url=base_url,
        token_manager=token_manager,
        payload_type=payload_type,
        max_retries=rf.DEFAULT_MAX_RETRIES,
        logger=logger,
    )
    ok_count = sum(1 for o in outcomes if o["ok"])
    logger.info("Submission complete: %s/%s returned OK", ok_count, len(outcomes))

    # Persist the before-snapshot immediately so a later --recheck-from is possible.
    snap_path = output_dir("verify_single_entity_refresh") / (log_path.stem + ".snapshot.json")
    snap_path.write_text(
        json.dumps({"before": before, "submit_outcomes": outcomes, "cutoff": cutoff_date.isoformat()}, indent=2),
        encoding="utf-8",
    )
    logger.info("Snapshot written: %s (re-check later with --recheck-from %s)", snap_path, snap_path)

    logger.info("Polling up to %ss (every %ss) for pd_last_known_date to advance...", args.max_wait, args.interval)
    results = poll_until_refreshed(before, max_wait=args.max_wait, interval=args.interval, logger=logger)
    advanced, changed = print_table(results)

    result_path = output_dir("verify_single_entity_refresh") / (log_path.stem + ".result.json")
    result_path.write_text(
        json.dumps({
            "cutoff": cutoff_date.isoformat(),
            "submitted": len(external_ids),
            "submit_ok": ok_count,
            "pd_advanced": advanced,
            "updated_changed": changed,
            "results": results,
        }, indent=2),
        encoding="utf-8",
    )
    logger.info("Result JSON: %s", result_path)
    print(f"Re-check later with:\n  python test_single_entity_refresh.py --recheck-from {snap_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
