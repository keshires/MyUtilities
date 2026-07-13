"""
Reconcile a stale non-public entity refresh: re-run the same stale query used by
``refresh_stale_non_public_entities.py`` and export every entity that **still
matches** (i.e. was *not* updated by the last refresh) to a CSV, with the
``entity_data`` JSON column flattened into separate columns.

Read-only — queries Postgres only, no SSO and no API calls.

Two entity modes (``--entity-type``), mirroring the refresh script:

**custom**  — ``custom_id IS NOT NULL``
**private** — ``custom_id IS NULL`` (default)

Both keep ``data_type = 'Private'``, exclude tenant ``0014000000NXtS8``, and treat a
row as stale when the chosen ``--stale-date-column`` (``updated_date`` default or
``pd_last_known_date``) is NULL or ``< first of current month`` (override with
``--date-filter``; ignore with ``--all-entities``).

Entities whose ``financialStmtDate`` is older than ``--financial-max-age-years``
(default 3; ``0`` disables) are excluded — matching the refresh script so both
tools operate on the same population.

Examples:
  python validate_stale_entities.py --entity-type custom
  python validate_stale_entities.py --entity-type private --limit 100
  python validate_stale_entities.py --entity-type custom --date-filter 2026-06-01
  python validate_stale_entities.py --entity-type custom --tenant-id 0014000000ABC123
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

from project_paths import logs_dir, output_dir, resolve_cli_artifact

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_EXCLUDED_TENANTS = ("0014000000NXtS8",)
CURSOR_PREFETCH = 20000

POSTGRES_ENV_KEYS = (
    "TESSERA_POSTGRES_HOST",
    "TESSERA_POSTGRES_DB",
    "TESSERA_POSTGRES_USER",
    "TESSERA_POSTGRES_PASSWORD",
)

CUSTOM_ID_CLAUSE = {
    "custom": "custom_id IS NOT NULL",
    "private": "custom_id IS NULL",
}

# Kept in sync with refresh_stale_non_public_entities.py.
STALE_DATE_COLUMNS = ("updated_date", "pd_last_known_date")
DEFAULT_STALE_DATE_COLUMN = "updated_date"
DEFAULT_FINANCIAL_STMT_MAX_AGE_YEARS = 3


def resolve_stale_date_column(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    if not key:
        return DEFAULT_STALE_DATE_COLUMN
    if key not in STALE_DATE_COLUMNS:
        valid = ", ".join(STALE_DATE_COLUMNS)
        raise SystemExit(f"Invalid --stale-date-column {raw!r}. Choose one of: {valid}")
    return key


def financial_stmt_clause(max_age_years: int) -> str:
    """financialStmtDate gate; ``max_age_years <= 0`` disables it. Mirrors the
    refresh script so both tools select the same population."""
    if max_age_years <= 0:
        return ""
    return (
        "AND (\n"
        "        NULLIF(entity_data ->> 'financialStmtDate', '') IS NULL\n"
        "        OR NULLIF(entity_data ->> 'financialStmtDate', '')::timestamp"
        f" >= (NOW() - INTERVAL '{max_age_years} years')\n"
        "      )"
    )

# Fixed top-level keys of entity_data, confirmed against production. Any key not
# listed here is preserved in the attributes_extra_json overflow column.
ENTITY_DATA_KEYS = [
    "found",
    "hasPgs",
    "isBank",
    "peerId",
    "country",
    "loading",
    "modelId",
    "industry",
    "ewsChange",
    "pdTrigger",
    "dataSource",
    "pdBpsChange",
    "hasScorecard",
    "industryCode",
    "isPeerDriven",
    "capOneYrTTCIr",
    "capOneYrTTCPd",
    "peerGroupName",
    "confidenceCode",
    "entityLegalForm",
    "hasCustomProfile",
    "financialStmtDate",
    "hasCustomPeerGroup",
    "hasCustomFinancials",
    "impliedRatingChange",
    "hasAnyCustomizations",
    "confidenceDescription",
    "peerGroupPdPercentile",
    "replacementIdentifier",
    "industryClassification",
]

CORE_COLUMNS = [
    "entity_type",
    "external_id",
    "name",
    "tenant_id",
    "custom_id",
    "updated_date",
    "pd_last_known_date",
    "as_of_date",
    "days_since_updated",
]

CSV_FIELDNAMES = CORE_COLUMNS + ENTITY_DATA_KEYS + ["attributes_extra_json"]
_KNOWN_KEYS = set(ENTITY_DATA_KEYS)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def resolve_entity_type(raw: str | None) -> str:
    key = (raw or _env("STALE_REFRESH_ENTITY_TYPE", "private")).strip().lower()
    aliases = {"customized": "custom", "customised": "custom"}
    key = aliases.get(key, key)
    if key not in CUSTOM_ID_CLAUSE:
        valid = ", ".join(sorted(CUSTOM_ID_CLAUSE))
        raise SystemExit(f"Invalid --entity-type {raw!r}. Choose one of: {valid}")
    return key


def excluded_tenant_ids() -> list[str]:
    raw = _env("STALE_REFRESH_EXCLUDED_TENANTS")
    if raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    return list(DEFAULT_EXCLUDED_TENANTS)


def first_of_current_month() -> date:
    return date.today().replace(day=1)


def missing_postgres_env() -> list[str]:
    return [key for key in POSTGRES_ENV_KEYS if not _env(key)]


def setup_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("validate_stale_entities")
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
    entity_type: str,
    *,
    tenant_id: str | None,
    include_all: bool,
    stale_date_column: str = DEFAULT_STALE_DATE_COLUMN,
    financial_max_age_years: int = DEFAULT_FINANCIAL_STMT_MAX_AGE_YEARS,
) -> str:
    """Same WHERE clause as the refresh script's stale query, per-row detail."""
    custom_clause = CUSTOM_ID_CLAUSE[entity_type]
    if include_all:
        tenant_ph = "$1"
        date_clause = ""
    else:
        tenant_ph = "$2"
        date_clause = (
            f"AND ({stale_date_column} IS NULL OR {stale_date_column} < $1::timestamp)"
        )
    if tenant_id:
        tenant_clause = f"tenant_id = {tenant_ph}::text"
    else:
        tenant_clause = f"tenant_id <> ALL({tenant_ph}::text[])"
    fin_clause = financial_stmt_clause(financial_max_age_years)
    return f"""
SELECT external_id, name, tenant_id, custom_id, updated_date, pd_last_known_date, as_of_date, entity_data
FROM public.entity
WHERE data_type = 'Private'
  AND {custom_clause}
  AND external_id IS NOT NULL
  AND {tenant_clause}
  {fin_clause}
  {date_clause}
ORDER BY external_id
"""


def _cell(value: object) -> str:
    """Render a JSON scalar for CSV. Nested objects/arrays become JSON text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _parse_entity_data(raw: object) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def build_csv_row(record: asyncpg.Record, *, entity_type: str, run_day: date) -> tuple[dict[str, str], bool, bool]:
    """Return (row, entity_data_missing, used_overflow)."""
    updated = record["updated_date"]
    pd_last_known = record["pd_last_known_date"]
    as_of = record["as_of_date"]
    days_since = ""
    if updated is not None:
        days_since = str((run_day - updated.date()).days)

    ed = _parse_entity_data(record["entity_data"])
    entity_data_missing = ed is None
    ed = ed or {}

    row: dict[str, str] = {
        "entity_type": entity_type,
        "external_id": _cell(record["external_id"]),
        "name": _cell(record["name"]),
        "tenant_id": _cell(record["tenant_id"]),
        "custom_id": _cell(record["custom_id"]),
        "updated_date": updated.isoformat() if updated is not None else "",
        "pd_last_known_date": pd_last_known.isoformat() if pd_last_known is not None else "",
        "as_of_date": as_of.isoformat() if as_of is not None else "",
        "days_since_updated": days_since,
    }
    for key in ENTITY_DATA_KEYS:
        row[key] = _cell(ed.get(key))

    extra = {k: v for k, v in ed.items() if k not in _KNOWN_KEYS}
    row["attributes_extra_json"] = json.dumps(extra, ensure_ascii=False) if extra else ""
    return row, entity_data_missing, bool(extra)


async def export_reconciliation(
    *,
    entity_type: str,
    tenant_id: str | None,
    include_all: bool,
    date_filter: date,
    excluded_tenants: list[str],
    stale_date_column: str,
    financial_max_age_years: int,
    limit: int | None,
    out_csv: Path,
    logger: logging.Logger,
) -> dict[str, int]:
    query = build_query(
        entity_type,
        tenant_id=tenant_id,
        include_all=include_all,
        stale_date_column=stale_date_column,
        financial_max_age_years=financial_max_age_years,
    )
    tenant_param = tenant_id if tenant_id else excluded_tenants
    cutoff = datetime.combine(date_filter, datetime.min.time())
    run_day = date.today()

    stats = {
        "rows_written": 0,
        "null_updated_date": 0,
        "missing_entity_data": 0,
        "rows_with_overflow": 0,
    }

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    conn = await pg_connect()
    try:
        with out_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
            writer.writeheader()

            async with conn.transaction():
                if include_all:
                    cursor = conn.cursor(query, tenant_param, prefetch=CURSOR_PREFETCH)
                else:
                    cursor = conn.cursor(query, cutoff, tenant_param, prefetch=CURSOR_PREFETCH)

                async for record in cursor:
                    row, missing, used_overflow = build_csv_row(
                        record, entity_type=entity_type, run_day=run_day
                    )
                    writer.writerow(row)
                    stats["rows_written"] += 1
                    if record["updated_date"] is None:
                        stats["null_updated_date"] += 1
                    if missing:
                        stats["missing_entity_data"] += 1
                    if used_overflow:
                        stats["rows_with_overflow"] += 1

                    if stats["rows_written"] % 10000 == 0:
                        logger.info("Written %s rows so far", f"{stats['rows_written']:,}")

                    if limit is not None and stats["rows_written"] >= limit:
                        logger.info("Reached --limit %s; stopping", limit)
                        break
    finally:
        await conn.close()

    return stats


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--entity-type",
        default=None,
        help="'custom' (custom_id IS NOT NULL) or 'private' (custom_id IS NULL). "
        "Default: STALE_REFRESH_ENTITY_TYPE or 'private'.",
    )
    parser.add_argument(
        "--date-filter",
        type=str,
        default=None,
        help="Stale cutoff date (YYYY-MM-DD). Default: first day of current month.",
    )
    parser.add_argument(
        "--stale-date-column",
        type=str,
        default=None,
        choices=STALE_DATE_COLUMNS,
        help=(
            f"Column compared against the stale cutoff. Choices: {', '.join(STALE_DATE_COLUMNS)}. "
            f"Default: STALE_REFRESH_STALE_DATE_COLUMN or '{DEFAULT_STALE_DATE_COLUMN}'."
        ),
    )
    parser.add_argument(
        "--financial-max-age-years",
        type=int,
        default=int(
            os.getenv("STALE_REFRESH_FINANCIAL_MAX_AGE_YEARS", str(DEFAULT_FINANCIAL_STMT_MAX_AGE_YEARS))
        ),
        help=(
            "Only include entities whose financialStmtDate is missing or within this many "
            f"years of now (default: {DEFAULT_FINANCIAL_STMT_MAX_AGE_YEARS}). Use 0 to disable."
        ),
    )
    parser.add_argument(
        "--all-entities",
        action="store_true",
        help="Include all matching entities, not only those stale by --date-filter.",
    )
    parser.add_argument(
        "--tenant-id",
        type=str,
        default=None,
        help="Restrict to a single tenant_id (overrides tenant exclusion).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on rows written (testing).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="CSV path (default: output/stale_entities/stale_reconcile_<type>_<utc>.csv). "
        "Relative paths resolve under output/stale_entities/.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    entity_type = resolve_entity_type(args.entity_type)
    stale_date_column = resolve_stale_date_column(
        args.stale_date_column or _env("STALE_REFRESH_STALE_DATE_COLUMN")
    )
    financial_max_age_years = max(0, args.financial_max_age_years)

    run_started = datetime.now(timezone.utc)
    log_path = (
        logs_dir("validate_stale_entities")
        / f"validate_stale_entities_{entity_type}_{run_started.strftime('%Y%m%d_%H%M%S')}.log"
    )
    logger = setup_logging(log_path)

    missing = missing_postgres_env()
    if missing:
        logger.error("Missing Postgres settings in .env: %s", ", ".join(missing))
        return 1

    if args.date_filter:
        date_filter = datetime.strptime(args.date_filter, "%Y-%m-%d").date()
    else:
        date_filter = first_of_current_month()

    tenant_id = (args.tenant_id or "").strip() or None
    excluded = excluded_tenant_ids()

    if args.output is None:
        ts = run_started.strftime("%Y%m%d_%H%M%S")
        out_csv = output_dir("validate_stale_entities") / f"stale_reconcile_{entity_type}_{ts}.csv"
    else:
        out_csv = resolve_cli_artifact(args.output, "validate_stale_entities")

    logger.info("Run started")
    logger.info("Entity type: %s", entity_type)
    logger.info("Log file: %s", log_path)
    if args.all_entities:
        logger.info("Including all entities (ignoring stale date filter)")
    else:
        logger.info("Stale cutoff (%s <): %s", stale_date_column, date_filter.isoformat())
    logger.info(
        "Financial statement max age: %s",
        f"{financial_max_age_years} years" if financial_max_age_years > 0 else "disabled",
    )
    if tenant_id:
        logger.info("Tenant filter: %s", tenant_id)
    else:
        logger.info("Excluded tenant_id values: %s", excluded)
    logger.info("Output CSV: %s", out_csv)
    logger.info(
        "SQL query:\n%s",
        build_query(
            entity_type,
            tenant_id=tenant_id,
            include_all=args.all_entities,
            stale_date_column=stale_date_column,
            financial_max_age_years=financial_max_age_years,
        ),
    )

    try:
        stats = asyncio.run(
            export_reconciliation(
                entity_type=entity_type,
                tenant_id=tenant_id,
                include_all=args.all_entities,
                date_filter=date_filter,
                excluded_tenants=excluded,
                stale_date_column=stale_date_column,
                financial_max_age_years=financial_max_age_years,
                limit=args.limit,
                out_csv=out_csv,
                logger=logger,
            )
        )
    except Exception as exc:  # noqa: BLE001 — surface any DB/IO failure in the log
        logger.exception("Reconciliation export failed: %s", exc)
        return 1

    elapsed = (datetime.now(timezone.utc) - run_started).total_seconds()
    summary = {
        "entity_type": entity_type,
        "tenant_id": tenant_id,
        "include_all_entities": args.all_entities,
        "stale_date_column": stale_date_column,
        "financial_max_age_years": financial_max_age_years,
        "date_filter": date_filter.isoformat(),
        "output_csv": str(out_csv),
        **stats,
        "elapsed_seconds": round(elapsed, 2),
    }
    logger.info("Run summary: %s", json.dumps(summary, indent=2))

    summary_path = log_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps({"summary": summary}, indent=2), encoding="utf-8")
    logger.info("Summary JSON: %s", summary_path)

    if stats["rows_written"] == 0:
        print(f"\nNo stale {entity_type} entities still matching — nothing to reconcile.\n")
    else:
        print(
            f"\nWrote {stats['rows_written']:,} still-stale {entity_type} row(s) to {out_csv}\n"
        )
        if stats["rows_with_overflow"]:
            print(
                f"  Note: {stats['rows_with_overflow']:,} row(s) had extra entity_data keys "
                "in attributes_extra_json — consider promoting them to columns.\n"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
