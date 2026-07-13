"""
Only **Excel ``external_id`` values** define the lookup set — nothing else from
Postgres.

For each Excel id, looks at **all** ``public.entity`` rows with that
``external_id`` (typically **one row per ``tenant_id``**, sometimes more with
different ``as_of_date``). The id is **not updated** (stale) only when **none**
of those rows has non-null ``updated_date`` within the last N days — if **any**
tenant’s row was updated in that window, the ``external_id`` is treated as fresh
and is omitted. Output is **distinct** ``external_id`` only (single-column CSV).

Uses ``TESSERA_POSTGRES_*`` from environment or project root .env (python-dotenv).

Example:
  python export_stale_entities_from_excel.py ^
    --input "C:\\Github\\MyUtilities\\Day2Day_Utillites\\inputfiles\\StaleEntityRefresh\\Entit_Refresh_Queue_Data_May8th.xlsx"
  # Default CSV: output/stale_entities/stale_external_ids_<utc>.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import pandas as pd
from dotenv import load_dotenv

from project_paths import input_dir, output_dir, resolve_cli_artifact

log = logging.getLogger(__name__)

BATCH_SIZE = 2500

_EXCEL_EXTERNAL_ID_HEADERS = frozenset({"external_id", "externalid", "external id"})


def _load_dotenv() -> None:
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)


def _pick_external_id_column(columns: list[object]) -> str:
    for c in columns:
        key = str(c).strip().lower().replace(" ", "_")
        if key in _EXCEL_EXTERNAL_ID_HEADERS:
            return str(c)
    raise SystemExit(
        "Excel must contain an external_id column (e.g. external_id, external_Id). "
        f"Found: {list(columns)}"
    )


def load_external_ids(xlsx_path: Path) -> list[str]:
    log.info("Reading external_id column from %s", xlsx_path)
    head = pd.read_excel(xlsx_path, nrows=0)
    col = _pick_external_id_column(list(head.columns))
    log.info("Using column %r", col)
    df = pd.read_excel(xlsx_path, usecols=[col])
    s = df[col].dropna().astype(str).str.strip()
    s = s[s != ""]
    unique_ids = sorted(set(s))
    log.info(
        "Excel rows=%s nonempty=%s distinct_external_id=%s",
        len(df),
        int(s.shape[0]),
        len(unique_ids),
    )
    return unique_ids


async def pg_connect() -> asyncpg.Connection:
    return await asyncpg.connect(
        host=os.environ["TESSERA_POSTGRES_HOST"],
        port=int(os.getenv("TESSERA_POSTGRES_PORT", "5432")),
        database=os.environ["TESSERA_POSTGRES_DB"],
        user=os.environ["TESSERA_POSTGRES_USER"],
        password=os.environ["TESSERA_POSTGRES_PASSWORD"],
        ssl="prefer",
    )


async def fetch_stale_external_ids_batch(
    conn: asyncpg.Connection, ids_batch: list[str], stale_days: int
) -> list[str]:
    # Same external_id => many rows (per tenant_id, etc.). Distinct external_id
    # is stale only if *no* row has non-null updated_date within the window.
    sql = f"""
        SELECT inp.input_external_id AS external_id
        FROM unnest($1::text[]) AS inp(input_external_id)
        WHERE EXISTS (
            SELECT 1
            FROM entity AS e
            WHERE e.external_id = inp.input_external_id
              AND e.external_id IS NOT NULL
        )
          AND NOT EXISTS (
            SELECT 1
            FROM entity AS e
            WHERE e.external_id = inp.input_external_id
              AND e.external_id IS NOT NULL
              AND e.updated_date IS NOT NULL
              AND e.updated_date >= (CURRENT_TIMESTAMP - INTERVAL '{int(stale_days)} days')
          )
    """
    rows = await conn.fetch(sql, ids_batch)
    allowed = set(ids_batch)
    out: list[str] = []
    for r in rows:
        val = r["external_id"]
        if val is not None and val in allowed:
            out.append(val)
    return out


async def export_stale_distinct_external_ids(
    *,
    xlsx_path: Path,
    out_csv: Path,
    stale_days: int,
) -> int:
    ids = load_external_ids(xlsx_path)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    if not ids:
        log.warning("No external_id values found; writing header only")
        out_csv.write_text("external_id\n", encoding="utf-8")
        return 0

    conn = await pg_connect()
    rows_written = 0
    try:
        with out_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["external_id"])
            for start in range(0, len(ids), BATCH_SIZE):
                batch = ids[start : start + BATCH_SIZE]
                ext_ids = await fetch_stale_external_ids_batch(conn, batch, stale_days)
                for eid in ext_ids:
                    w.writerow([eid])
                    rows_written += 1
                if (start // BATCH_SIZE) % 20 == 0 and start > 0:
                    log.info(
                        "Processed ids %s/%s, stale_external_ids_written=%s",
                        start,
                        len(ids),
                        rows_written,
                    )
        log.info(
            "Done. Distinct stale external_id rows (data)=%s -> %s",
            rows_written,
            out_csv,
        )
        return rows_written
    finally:
        await conn.close()


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parent
    p.add_argument(
        "--input",
        type=Path,
        default=input_dir("export_stale_entities")
        / "Entit_Refresh_Queue_Data_May8th.xlsx",
        help="Excel file containing column external_id",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "CSV path (default: output/stale_entities/stale_external_ids_<utc>.csv). "
            "Relative paths are under output/stale_entities/."
        ),
    )
    p.add_argument(
        "--stale-days",
        type=int,
        default=10,
        help=(
            "Include external_id only if no entity row (any tenant_id) has "
            "updated_date within this many days"
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _load_dotenv()
    missing = [
        k
        for k in (
            "TESSERA_POSTGRES_HOST",
            "TESSERA_POSTGRES_DB",
            "TESSERA_POSTGRES_USER",
            "TESSERA_POSTGRES_PASSWORD",
        )
        if not os.getenv(k)
    ]
    if missing:
        log.error("Missing env: %s", ", ".join(missing))
        return 2

    args = parse_args(argv)
    if not args.input.is_file():
        log.error("Input not found: %s", args.input)
        return 1

    if args.output is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        args.output = output_dir("export_stale_entities") / f"stale_external_ids_{ts}.csv"
    else:
        args.output = resolve_cli_artifact(args.output, "export_stale_entities")

    n = asyncio.run(
        export_stale_distinct_external_ids(
            xlsx_path=args.input, out_csv=args.output, stale_days=args.stale_days
        )
    )
    print(f"Wrote {n} distinct stale external_id value(s) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
