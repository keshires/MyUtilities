"""
Postgres helper: load portfolio ids from table "portfolio" (default PK column id, tenant Tenant_Id;
override PORTFOLIO_ID_COLUMN / PORTFOLIO_TENANT_COLUMN if your DDL differs),
then call calculate_portfolio_kpis(integer) per id, or list/export only.

Config: TESSERA_POSTGRES_HOST, TESSERA_POSTGRES_PORT (5432), TESSERA_POSTGRES_DB,
TESSERA_POSTGRES_USER, TESSERA_POSTGRES_PASSWORD — from env or .env (python-dotenv).

Optional env: PORTFOLIO_TABLE, PORTFOLIO_ID_COLUMN (id), PORTFOLIO_TENANT_COLUMN (Tenant_Id),
KPI_FUNCTION_SCHEMA (public), KPI_LOG_FILE (else ``logs/run_portfolio_kpis_postgres_*.log`` under the project root; relative paths are from project root).

Requires: asyncpg; optional: python-dotenv. Short doc: Docs/run-portfolio-kpis-postgres.md
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import socket
import sys
import time
import traceback
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from project_paths import (
    PROJECT_ROOT,
    logs_dir,
    resolve_cli_artifact,
    resolve_project_relative,
)


def _load_dotenv_from_project_root() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)


try:
    import asyncpg
except ImportError as exc:  # pragma: no cover
    raise SystemExit("asyncpg is required. Install with: pip install asyncpg") from exc


@dataclass(frozen=True)
class PostgresSettings:
    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_env(cls) -> PostgresSettings:
        missing = [
            name
            for name in (
                "TESSERA_POSTGRES_HOST",
                "TESSERA_POSTGRES_DB",
                "TESSERA_POSTGRES_USER",
                "TESSERA_POSTGRES_PASSWORD",
            )
            if not os.getenv(name)
        ]
        if missing:
            raise SystemExit(
                "Missing required environment variables: "
                + ", ".join(missing)
                + "\nSet TESSERA_POSTGRES_* before running this script."
            )
        port_raw = os.getenv("TESSERA_POSTGRES_PORT", "5432")
        try:
            port = int(port_raw)
        except ValueError as e:
            raise SystemExit(
                f"TESSERA_POSTGRES_PORT must be an integer, got {port_raw!r}"
            ) from e
        return cls(
            host=os.environ["TESSERA_POSTGRES_HOST"],
            port=port,
            database=os.environ["TESSERA_POSTGRES_DB"],
            user=os.environ["TESSERA_POSTGRES_USER"],
            password=os.environ["TESSERA_POSTGRES_PASSWORD"],
        )


def _log_connection_diagnostics(
    logger: logging.Logger, host: str, port: int, error_type: str, error_msg: str
) -> None:
    logger.error("Diagnostics:")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        logger.error("  DNS resolve: OK (%d address(es))", len(infos))
    except OSError as dns_exc:
        logger.error("  DNS resolve: FAILED — %s", dns_exc)
    logger.error(
        "  Tip: verify host/port, VPN, firewall, and that Postgres accepts your client IP."
    )


async def get_connection(
    settings: PostgresSettings,
    logger: logging.Logger,
) -> AsyncGenerator[asyncpg.Connection, None]:
    """Yield an asyncpg connection with structured error logging on failure."""
    conn: asyncpg.Connection | None = None
    connection_start_time = time.perf_counter()
    host, port, database, user = (
        settings.host,
        settings.port,
        settings.database,
        settings.user,
    )
    try:
        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            password=settings.password,
            database=database,
            timeout=60,
        )
        yield conn
    except Exception as e:
        total_time = time.perf_counter() - connection_start_time
        error_type = type(e).__name__
        error_msg = str(e) if str(e) else "(no error message)"
        logger.error("")
        logger.error("=" * 80)
        logger.error("POSTGRESQL CONNECTION FAILED")
        logger.error("=" * 80)
        logger.error("Error Type: %s", error_type)
        logger.error("Error Message: %s", error_msg)
        logger.error("Time Elapsed: %.3fs", total_time)
        logger.error("")
        logger.error("Connection Details:")
        logger.error("  Host: %s", host)
        logger.error("  Port: %s", port)
        logger.error("  Database: %s", database)
        logger.error("  User: %s", user)
        logger.error("")
        _log_connection_diagnostics(logger, host, port, error_type, error_msg)
        logger.error("=" * 80)
        logger.error("Full Stack Trace:", exc_info=True)
        logger.error("=" * 80)
        raise
    finally:
        if conn is not None:
            try:
                await conn.close()
                logger.debug("Database connection closed")
            except Exception as close_exc:
                logger.warning("Error closing database connection: %s", close_exc)


def _setup_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("portfolio_kpi_batch")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def _validate_sql_identifier(name: str, label: str) -> None:
    safe = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
    if not name or any(c not in safe for c in name):
        raise ValueError(f"Invalid {label}: {name!r}")


async def fetch_portfolio_ids(
    conn: asyncpg.Connection,
    table: str,
    id_column: str,
    tenant_column: str,
    tenant_id: str | None,
    logger: logging.Logger,
) -> list[int]:
    """Load portfolio ids from the portfolio table, optionally filtered by tenant."""
    _validate_sql_identifier(table, "PORTFOLIO_TABLE")
    _validate_sql_identifier(id_column, "PORTFOLIO_ID_COLUMN")

    if tenant_id is not None:
        _validate_sql_identifier(tenant_column, "PORTFOLIO_TENANT_COLUMN")
        sql = (
            f'SELECT "{id_column}" AS pid FROM "{table}" '
            f'WHERE "{tenant_column}" = $1 ORDER BY "{id_column}"'
        )
        rows = await conn.fetch(sql, tenant_id)
        logger.info(
            "Loaded %d portfolio id(s) from %s (tenant %s = %s)",
            len(rows),
            table,
            tenant_column,
            tenant_id,
        )
    else:
        sql = f'SELECT "{id_column}" AS pid FROM "{table}" ORDER BY "{id_column}"'
        rows = await conn.fetch(sql)
        logger.info("Loaded %d portfolio id(s) from %s (all tenants)", len(rows), table)

    return [int(r["pid"]) for r in rows]


def _log_full_portfolio_list(
    logger: logging.Logger, portfolio_ids: list[int], label: str
) -> None:
    logger.info("FULL_PORTFOLIO_LIST_BEGIN (%s) count=%d", label, len(portfolio_ids))
    for pid in portfolio_ids:
        logger.info("portfolio_id=%s", pid)
    logger.info("FULL_PORTFOLIO_LIST_END")


def _export_portfolio_ids_csv(
    path: Path, portfolio_ids: list[int], logger: logging.Logger
) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["portfolio_id"])
        for pid in portfolio_ids:
            w.writerow([pid])
    logger.info("Exported %d portfolio_id(s) to %s", len(portfolio_ids), path.resolve())


@dataclass(frozen=True)
class RunOptions:
    portfolio_ids_override: list[int] | None
    tenant_id: str | None
    list_only: bool
    export_list_path: Path | None


def _sanitize_log_filename_fragment(s: str, max_len: int = 120) -> str:
    """Keep a single path segment safe on Windows and readable."""
    bad = '<>:"/\\|?*'
    for c in bad:
        s = s.replace(c, "_")
    s = "_".join(p for p in s.replace(" ", "_").split("_") if p)
    if len(s) > max_len:
        s = s[:max_len].rstrip("_")
    return s or "run"


def default_kpi_log_path(options: RunOptions) -> Path:
    """Default log path: logs/<script_stem>_<YYYYMMDD_HHMMSS>_<scope>_<mode>.log (UTC)."""
    script_stem = Path(__file__).resolve().stem
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if options.portfolio_ids_override is not None:
        ids = options.portfolio_ids_override
        if len(ids) == 1:
            scope = f"pid{ids[0]}"
        elif len(ids) <= 5:
            scope = "pids_" + "_".join(str(i) for i in ids)
        else:
            head = "_".join(str(i) for i in ids[:3])
            scope = f"pids_n{len(ids)}_{head}_etc"
    elif options.tenant_id is not None:
        scope = _sanitize_log_filename_fragment(
            f"tenant_{options.tenant_id}", max_len=80
        )
    else:
        scope = "all_rows"

    mode_parts: list[str] = []
    if options.list_only:
        mode_parts.append("listonly")
    else:
        mode_parts.append("kpi")
    if options.export_list_path is not None:
        mode_parts.append("export")

    param = _sanitize_log_filename_fragment(f"{scope}_{'_'.join(mode_parts)}")
    return logs_dir("run_portfolio_kpis") / f"{script_stem}_{ts}_{param}.log"


async def calculate_portfolio_kpis(
    conn: asyncpg.Connection, portfolio_id: int, schema: str
) -> None:
    """Invoke DB function calculate_portfolio_kpis(integer)."""
    safe = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
    if not schema or any(c not in safe for c in schema):
        raise ValueError(f"Invalid KPI_FUNCTION_SCHEMA: {schema!r}")
    # asyncpg requires function calls in SQL text; schema is validated above.
    await conn.execute(
        f"SELECT {schema}.calculate_portfolio_kpis($1::integer)", portfolio_id
    )


def _parse_portfolio_ids_cli(args: argparse.Namespace) -> list[int] | None:
    """Return explicit id list from --portfolio-id / --portfolio-ids, or None to load from DB."""
    raw: list[int] = []
    if args.portfolio_id:
        raw.extend(args.portfolio_id)
    if args.portfolio_ids_csv:
        for part in args.portfolio_ids_csv.split(","):
            part = part.strip()
            if part:
                raw.append(int(part, 10))
    if not raw:
        return None
    seen: set[int] = set()
    ordered: list[int] = []
    for pid in raw:
        if pid not in seen:
            seen.add(pid)
            ordered.append(pid)
    return ordered


async def run_batch(options: RunOptions) -> int:
    settings = PostgresSettings.from_env()
    table = os.getenv("PORTFOLIO_TABLE", "portfolio")
    id_column = os.getenv("PORTFOLIO_ID_COLUMN", "id")
    tenant_column = os.getenv("PORTFOLIO_TENANT_COLUMN", "Tenant_Id").strip()
    schema = os.getenv("KPI_FUNCTION_SCHEMA", "public")

    log_file = os.getenv("KPI_LOG_FILE")
    log_path = (
        Path(resolve_project_relative(log_file))
        if (log_file or "").strip()
        else default_kpi_log_path(options)
    )
    logger = _setup_logging(log_path)

    logger.info("Log file: %s", log_path.resolve())
    logger.info(
        "Table=%s id_column=%s tenant_column=%s KPI schema=%s",
        table,
        id_column,
        tenant_column,
        schema,
    )
    if options.tenant_id is not None:
        logger.info("Tenant filter active: %s = %s", tenant_column, options.tenant_id)
    if options.portfolio_ids_override is not None:
        logger.info(
            "Mode: explicit portfolio id(s) from CLI — %s",
            options.portfolio_ids_override,
        )
    if options.list_only:
        logger.info("Mode: --list-only (no calculate_portfolio_kpis calls)")

    exit_code = 0
    success = 0
    failures = 0
    batch_started = time.perf_counter()
    resolved_ids: list[int] = []

    if options.list_only and options.portfolio_ids_override is not None:
        if options.tenant_id is not None:
            raise SystemExit(
                "Cannot combine --tenant-id with explicit --portfolio-id / --portfolio-ids."
            )
        resolved_ids = list(options.portfolio_ids_override)
        _log_full_portfolio_list(logger, resolved_ids, "explicit CLI ids")
        if options.export_list_path is not None:
            _export_portfolio_ids_csv(options.export_list_path, resolved_ids, logger)
    else:
        async for conn in get_connection(settings, logger):
            if options.portfolio_ids_override is not None:
                resolved_ids = list(options.portfolio_ids_override)
                logger.info(
                    "Processing %d portfolio id(s) (no table scan)", len(resolved_ids)
                )
            else:
                resolved_ids = await fetch_portfolio_ids(
                    conn,
                    table,
                    id_column,
                    tenant_column,
                    options.tenant_id,
                    logger,
                )

            if not resolved_ids:
                logger.warning("No portfolio rows found; nothing to do.")
                break

            if options.export_list_path is not None:
                _export_portfolio_ids_csv(
                    options.export_list_path, resolved_ids, logger
                )

            if options.list_only:
                label = (
                    "all rows in table"
                    if options.tenant_id is None
                    else f"tenant {options.tenant_id}"
                )
                _log_full_portfolio_list(logger, resolved_ids, label)
                break

            for portfolio_id in resolved_ids:
                t0 = time.perf_counter()
                logger.info("--- PortfolioId=%s | request started ---", portfolio_id)
                try:
                    await calculate_portfolio_kpis(conn, portfolio_id, schema)
                    elapsed = time.perf_counter() - t0
                    success += 1
                    logger.info(
                        "PortfolioId=%s | SUCCESS | processing_time_sec=%.4f",
                        portfolio_id,
                        elapsed,
                    )
                except Exception:
                    elapsed = time.perf_counter() - t0
                    failures += 1
                    exit_code = 1
                    logger.error(
                        "PortfolioId=%s | FAILED | processing_time_sec=%.4f",
                        portfolio_id,
                        elapsed,
                    )
                    logger.error(traceback.format_exc())

    total_elapsed = time.perf_counter() - batch_started
    logger.info("")
    logger.info("=" * 80)
    if options.list_only:
        logger.info("LIST SUMMARY")
        logger.info("=" * 80)
        logger.info("Total wall time: %.4f s", total_elapsed)
        logger.info("Portfolio id count: %d", len(resolved_ids))
    else:
        logger.info("BATCH SUMMARY")
        logger.info("=" * 80)
        logger.info("Total wall time (batch): %.4f s", total_elapsed)
        logger.info("Successes: %d", success)
        logger.info("Failures:  %d", failures)
    logger.info("Log file:  %s", log_path.resolve())
    logger.info("=" * 80)

    return exit_code


def main() -> None:
    _load_dotenv_from_project_root()
    parser = argparse.ArgumentParser(
        description="Postgres: list portfolio ids and/or run calculate_portfolio_kpis per id.",
    )
    parser.add_argument(
        "--portfolio-id",
        type=int,
        action="append",
        dest="portfolio_id",
        metavar="ID",
        help="Run only this portfolio id (repeat for multiple). Skips reading the portfolio table.",
    )
    parser.add_argument(
        "--portfolio-ids",
        type=str,
        dest="portfolio_ids_csv",
        metavar="CSV",
        help="Comma-separated portfolio ids (alternative to repeated --portfolio-id).",
    )
    parser.add_argument(
        "--tenant-id",
        type=str,
        default=None,
        metavar="TENANT",
        help="Only load portfolio rows where PORTFOLIO_TENANT_COLUMN (default Tenant_Id) equals this value (requires DB read).",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Load portfolio id(s) and log the full list; do not call calculate_portfolio_kpis.",
    )
    parser.add_argument(
        "--export-list",
        type=Path,
        default=None,
        metavar="CSV_PATH",
        help=(
            "Write portfolio_id column to this CSV after ids are resolved. "
            "Relative paths go under output/portfolio/ at the project root."
        ),
    )
    args = parser.parse_args()
    override = _parse_portfolio_ids_cli(args)
    tenant_id = (args.tenant_id or "").strip() or None
    if tenant_id is not None and override is not None:
        parser.error(
            "Cannot combine --tenant-id with --portfolio-id / --portfolio-ids."
        )
    export_path = args.export_list
    if export_path is not None:
        export_path = resolve_cli_artifact(export_path, "run_portfolio_kpis")
    options = RunOptions(
        portfolio_ids_override=override,
        tenant_id=tenant_id,
        list_only=args.list_only,
        export_list_path=export_path,
    )
    try:
        code = asyncio.run(run_batch(options))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        code = 130
    raise SystemExit(code)


if __name__ == "__main__":
    main()
