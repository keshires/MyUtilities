"""PD-aware pre-check report (read-only). For a chosen --entity-type, classify every
stale entity (by pd_last_known_date) into POST/SKIP buckets and write a categorized
CSV + summary JSON. Never posts anything.

  private / custom : /edfx/v1/entities/pds (custom uses <externalId>-<financialsProcessId>);
                     pds "no data" -> /entity/v1/mapping; empty mapping => orphaned
                     (written to a separate delete-candidate CSV).
  public           : DB-only — fresh if pd_last_known_date is in the current month and
                     legal status is null/Active; report-only (never posted).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

import pd_precheck as pc
import refresh_stale_non_public_entities as rf
from project_paths import logs_dir, output_dir

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_EXCLUDED = ("001aJ00000Cwqc2QAB",)
PDS_BATCH = 200
END_DATE = None  # set per-run to first-of-next-day (today); see main()


def summarize(classified: list[tuple[pc.StaleRow, pc.Classification]], entity_type: str) -> dict:
    cats = Counter(c.category for _, c in classified)
    by_tenant: Counter = Counter(r.tenant_id for r, _ in classified)
    post = sum(1 for _, c in classified if c.action == "POST")
    skip = sum(1 for _, c in classified if c.action == "SKIP")
    return {
        "entity_type": entity_type,
        "stale_found": len(classified),
        "expected_to_refresh": post if entity_type in pc.POSTABLE_TYPES else 0,
        "post": post,
        "skip": skip,
        "orphaned": cats.get("orphaned", 0),
        "by_category": dict(cats),
        "by_tenant": dict(by_tenant),
    }


def _excluded() -> list[str]:
    raw = (os.getenv("STALE_REFRESH_EXCLUDED_TENANTS") or "").strip()
    return [x.strip() for x in raw.split(",") if x.strip()] or list(DEFAULT_EXCLUDED)


async def _pg():
    return await asyncpg.connect(
        host=os.environ["TESSERA_POSTGRES_HOST"], port=int(os.getenv("TESSERA_POSTGRES_PORT", "5432")),
        database=os.environ["TESSERA_POSTGRES_DB"], user=os.environ["TESSERA_POSTGRES_USER"],
        password=os.environ["TESSERA_POSTGRES_PASSWORD"], ssl="prefer",
    )


async def _fetch_rows(entity_type: str, ref: date, excluded: list[str], limit: int | None):
    """Returns (stale_rows, public_meta) — public_meta maps external_id -> legal_status
    (only populated for public)."""
    cutoff = datetime.combine(ref, datetime.min.time())
    lim = f"LIMIT {int(limit)}" if limit else ""
    conn = await _pg()
    try:
        if entity_type == "custom":
            q = f"""SELECT DISTINCT ON (e.external_id) e.external_id, e.tenant_id, e.custom_id,
                       e.pd_last_known_date, ecd.financials_process_id
                    FROM public.entity e
                    LEFT JOIN public.entity_custom_data ecd ON ecd.external_id = e.external_id
                    WHERE e.data_type='Private' AND e.custom_id IS NOT NULL AND e.external_id IS NOT NULL
                      AND e.tenant_id <> ALL($2::text[])
                      AND (NULLIF(e.entity_data->>'financialStmtDate','') IS NULL
                           OR NULLIF(e.entity_data->>'financialStmtDate','')::timestamp >= (NOW() - INTERVAL '3 years'))
                      AND (e.pd_last_known_date IS NULL OR e.pd_last_known_date < $1::timestamp)
                    ORDER BY e.external_id, e.pd_last_known_date DESC NULLS LAST {lim}"""
            rows = await conn.fetch(q, cutoff, excluded)
            stale = [pc.StaleRow(str(r["external_id"]), str(r["tenant_id"]), r["pd_last_known_date"],
                                 None, True, custom_id=str(r["custom_id"]),
                                 financials_process_id=str(r["financials_process_id"]) if r["financials_process_id"] else None)
                     for r in rows]
            return stale, {}
        if entity_type == "private":
            q = f"""SELECT DISTINCT ON (external_id) external_id, tenant_id, pd_last_known_date
                    FROM public.entity
                    WHERE data_type='Private' AND custom_id IS NULL AND external_id IS NOT NULL
                      AND tenant_id <> ALL($2::text[])
                      AND (NULLIF(entity_data->>'financialStmtDate','') IS NULL
                           OR NULLIF(entity_data->>'financialStmtDate','')::timestamp >= (NOW() - INTERVAL '3 years'))
                      AND (pd_last_known_date IS NULL OR pd_last_known_date < $1::timestamp)
                    ORDER BY external_id, pd_last_known_date DESC NULLS LAST {lim}"""
            rows = await conn.fetch(q, cutoff, excluded)
            return [pc.StaleRow(str(r["external_id"]), str(r["tenant_id"]), r["pd_last_known_date"],
                                None, False) for r in rows], {}
        # public
        q = f"""SELECT DISTINCT ON (external_id) external_id, tenant_id, pd_last_known_date, legal_status
                FROM public.entity
                WHERE data_type <> 'Private' AND external_id IS NOT NULL
                  AND tenant_id <> ALL($2::text[])
                  AND (pd_last_known_date IS NULL OR pd_last_known_date < $1::timestamp)
                ORDER BY external_id, pd_last_known_date DESC NULLS LAST {lim}"""
        rows = await conn.fetch(q, cutoff, excluded)
        stale = [pc.StaleRow(str(r["external_id"]), str(r["tenant_id"]), r["pd_last_known_date"],
                             None, False) for r in rows]
        meta = {str(r["external_id"]): r["legal_status"] for r in rows}
        return stale, meta
    finally:
        await conn.close()


def _http(logger):
    """Return (pds_post_batch, mapping_lookup) using SSO-authenticated calls."""
    tm = rf.TokenManager(sso_url=rf._env("MOODYS_SSO_URL", rf.DEFAULT_SSO_URL),
                         username=rf._env("MOODYS_SSO_USERNAME"), password=rf._env("MOODYS_SSO_PASSWORD"),
                         max_age_seconds=rf.TOKEN_MAX_AGE_SECONDS, logger=logger,
                         manual_token=rf._env("STALE_REFRESH_MANUAL_TOKEN") or None)
    tm.get_token()
    base = rf.tessera_base_url()
    session = rf.create_http_session(2)

    def hdr():
        return {"Authorization": f"Bearer {tm.get_token()}", "Content-Type": "application/json",
                "Accept": "application/json"}

    def pds_post(ids):
        payload = {"asyncResponse": False, "endDate": END_DATE, "modelParameters": {"fso": False},
                   "includeDetail": {"resultDetail": False, "inputDetail": False, "modelDetail": False,
                                     "includeTermStructure": False, "includeHistoryTermStructure": False},
                   "entities": [{"entityId": i} for i in ids]}
        r = session.post(f"{base}/edfx/v1/entities/pds", headers=hdr(), json=payload, verify=False, timeout=180)
        try:
            return json.loads(r.text).get("entities", [])
        except Exception:
            return []

    def mapping_lookup(external_ids):
        # Batched: an id is "found" if it appears in the mapping response body.
        queries = []
        for e in external_ids:
            queries.append({"entityId": e})
            queries.append({"customEntityIdentifier": e})
        r = session.post(f"{base}/entity/v1/mapping", headers=hdr(), json={"queries": queries},
                         verify=False, timeout=180)
        body = r.text or ""
        return {e for e in external_ids if e in body}

    return pds_post, mapping_lookup


def main(argv: list[str] | None = None) -> int:
    global END_DATE
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--entity-type", required=True, choices=["custom", "private", "public"])
    ap.add_argument("--date-filter", default=None, help="Stale cutoff YYYY-MM-DD (default 1st of month).")
    ap.add_argument("--limit", type=int, default=None, help="Cap entities (testing).")
    args = ap.parse_args(argv)

    ref = (datetime.strptime(args.date_filter, "%Y-%m-%d").date()
           if args.date_filter else pc.month_start(date.today()))
    END_DATE = date.today().isoformat()
    excluded = _excluded()
    et = args.entity_type

    log_path = logs_dir("validate_pd_precheck") / f"pd_precheck_{et}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.log"
    logger = rf.setup_logging(log_path)

    rows, public_meta = asyncio.run(_fetch_rows(et, ref, excluded, args.limit))
    logger.info("Stale %s: %s", et, len(rows))

    if et == "public":
        classified = [(r, pc.classify_public(r.pd_last_known_date, public_meta.get(r.external_id), ref))
                      for r in rows]
    else:
        pds_post, mapping_lookup = _http(logger)
        resolver = pc.PdMappingResolver(pds_post, mapping_lookup, batch_size=PDS_BATCH)
        statuses = resolver.resolve(rows, et)
        classified = [(r, pc.classify_status(et, statuses.get(r.external_id), ref)) for r in rows]

    summary = summarize(classified, et)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_csv = output_dir("validate_pd_precheck") / f"pd_precheck_{et}_{ts}.csv"
    orphan_csv = output_dir("validate_pd_precheck") / f"pd_precheck_{et}_{ts}.orphaned.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f, \
            orphan_csv.open("w", newline="", encoding="utf-8") as of:
        w = csv.writer(f); ow = csv.writer(of)
        w.writerow(["external_id", "tenant_id", "pd_last_known_date", "category", "action", "reason"])
        ow.writerow(["external_id", "tenant_id", "pd_last_known_date", "reason"])
        for r, c in classified:
            w.writerow([r.external_id, r.tenant_id, r.pd_last_known_date, c.category, c.action, c.reason])
            if c.category == "orphaned":
                ow.writerow([r.external_id, r.tenant_id, r.pd_last_known_date, c.reason])
    summary_path = log_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps({"summary": summary, "ref": ref.isoformat(),
                                        "output_csv": str(out_csv),
                                        "orphaned_csv": str(orphan_csv)}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"\nWrote {summary['stale_found']} rows to {out_csv}")
    if summary["orphaned"]:
        print(f"Orphaned (delete-candidates): {summary['orphaned']} -> {orphan_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
