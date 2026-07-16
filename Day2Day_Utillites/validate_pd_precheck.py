"""Read-only PD-aware pre-check report. For a chosen --entity-type, classify every
stale entity (by pd_last_known_date) as POST/SKIP with reason, using the peer-group
resolver, and write a categorized CSV + summary JSON. Never posts anything.
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
from project_paths import logs_dir, output_dir

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_EXCLUDED = ("001aJ00000Cwqc2QAB",)
CUSTOM_ID = {"custom": "custom_id IS NOT NULL", "private": "custom_id IS NULL"}


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
        "by_category": dict(cats),
        "by_tenant": dict(by_tenant),
    }


def _excluded() -> list[str]:
    raw = (os.getenv("STALE_REFRESH_EXCLUDED_TENANTS") or "").strip()
    return [x.strip() for x in raw.split(",") if x.strip()] or list(DEFAULT_EXCLUDED)


def _stale_query(entity_type: str) -> str:
    if entity_type in ("custom", "private"):
        data_type = "e.data_type = 'Private'"
        custom_clause = f"AND {CUSTOM_ID[entity_type]}"
    else:  # public
        data_type = "e.data_type <> 'Private'"
        custom_clause = ""
    return f"""
    SELECT e.external_id, e.tenant_id, e.pd_last_known_date,
           e.entity_data->>'peerId' AS peer_id,
           COALESCE(e.entity_data->>'isPeerDriven','') AS is_peer_driven
    FROM public.entity e
    WHERE {data_type} {custom_clause}
      AND e.external_id IS NOT NULL
      AND e.tenant_id <> ALL($2::text[])
      AND (NULLIF(e.entity_data->>'financialStmtDate','') IS NULL
           OR NULLIF(e.entity_data->>'financialStmtDate','')::timestamp >= (NOW()-INTERVAL '3 years'))
      AND (e.pd_last_known_date IS NULL OR e.pd_last_known_date < $1::timestamp)
    """


async def _pg():
    return await asyncpg.connect(
        host=os.environ["TESSERA_POSTGRES_HOST"], port=int(os.getenv("TESSERA_POSTGRES_PORT", "5432")),
        database=os.environ["TESSERA_POSTGRES_DB"], user=os.environ["TESSERA_POSTGRES_USER"],
        password=os.environ["TESSERA_POSTGRES_PASSWORD"], ssl="prefer",
    )


async def _fetch_rows(entity_type: str, ref: date, excluded: list[str]) -> list[pc.StaleRow]:
    conn = await _pg()
    try:
        rows = await conn.fetch(
            _stale_query(entity_type), datetime.combine(ref, datetime.min.time()), excluded
        )
    finally:
        await conn.close()
    return [
        pc.StaleRow(str(r["external_id"]), str(r["tenant_id"]), r["pd_last_known_date"],
                    r["peer_id"], r["is_peer_driven"] == "true")
        for r in rows
    ]


def _db_resolver() -> pc.DbMaxPeerGroupPdResolver:
    def fetch(ids: list[str]) -> list[tuple[str, date | None]]:
        async def run():
            conn = await _pg()
            try:
                q = """SELECT entity_data->>'peerId' pid, MAX(pd_last_known_date) mx
                       FROM public.entity WHERE entity_data->>'peerId' = ANY($1::text[])
                       GROUP BY 1"""
                return await conn.fetch(q, ids)
            finally:
                await conn.close()
        return [(str(r["pid"]), r["mx"]) for r in asyncio.run(run())]

    return pc.DbMaxPeerGroupPdResolver(fetch)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--entity-type", required=True, choices=["custom", "private", "public"])
    ap.add_argument("--date-filter", default=None, help="Stale cutoff YYYY-MM-DD (default 1st of month).")
    args = ap.parse_args(argv)

    ref = (datetime.strptime(args.date_filter, "%Y-%m-%d").date()
           if args.date_filter else pc.month_start(date.today()))
    excluded = _excluded()
    rows = asyncio.run(_fetch_rows(args.entity_type, ref, excluded))
    classified = pc.classify_all(rows, _db_resolver(), args.entity_type, ref)
    summary = summarize(classified, args.entity_type)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_csv = output_dir("validate_pd_precheck") / f"pd_precheck_{args.entity_type}_{ts}.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["external_id", "tenant_id", "pd_last_known_date", "peer_id",
                    "is_peer_driven", "category", "action", "reason", "group_fresh"])
        for r, c in classified:
            w.writerow([r.external_id, r.tenant_id, r.pd_last_known_date, r.peer_id,
                        r.is_peer_driven, c.category, c.action, c.reason, c.group_fresh])
    summary_path = logs_dir("validate_pd_precheck") / f"pd_precheck_{args.entity_type}_{ts}.summary.json"
    summary_path.write_text(
        json.dumps({"summary": summary, "ref": ref.isoformat(), "output_csv": str(out_csv)}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    print(f"\nWrote {summary['stale_found']} rows to {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
