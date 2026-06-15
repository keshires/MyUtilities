"""
Portfolio KPI update log metrics (Postgres).

Runs reports from Docs/portfolio-kpi-metrics.sql against public.portfolio_kpi_update_log.
Uses the same TESSERA_POSTGRES_* settings as run_portfolio_kpis_postgres.py (.env).

Examples:
  python portfolio_kpi_metrics_postgres.py --help
  python portfolio_kpi_metrics_postgres.py --start "2026-05-20 00:00:00" --end "2026-05-21 00:00:00" --report hourly
  python portfolio_kpi_metrics_postgres.py --start "2026-05-20 00:00:00" --end "2026-05-21 00:00:00" --report all
  python portfolio_kpi_metrics_postgres.py --start "2026-05-20 15:00:00" --end "2026-05-20 18:00:00" --report slow --source "Custom Financials"
  python portfolio_kpi_metrics_postgres.py --start "2026-05-20 00:00:00" --end "2026-05-21 00:00:00" --report hourly --export-csv hourly.csv

Doc: Docs/portfolio-kpi-metrics.md
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from project_paths import PROJECT_ROOT, resolve_cli_artifact

try:
    import asyncpg
except ImportError as exc:  # pragma: no cover
    raise SystemExit("asyncpg is required. Install with: pip install asyncpg") from exc

from run_portfolio_kpis_postgres import PostgresSettings, _load_dotenv_from_project_root

SQL_FILE = PROJECT_ROOT / "Docs" / "portfolio-kpi-metrics.sql"
REPORT_HEADER = re.compile(r"^--\s*REPORT:\s*(\w+)\s*$", re.MULTILINE)

REPORT_CHOICES = (
    "hourly",
    "hourly_by_status",
    "status",
    "slow",
    "slow_by_source",
    "all",
)

REPORT_ALIASES: dict[str, str] = {
    "hourly": "hourly_totals",
    "hourly_by_status": "hourly_by_status",
    "status": "status_summary",
    "slow": "slow_global",
    "slow_by_source": "slow_by_source",
}

ALL_REPORT_KEYS = (
    "hourly_totals",
    "hourly_by_status",
    "status_summary",
    "slow_global",
    "slow_by_source",
)


def _format_ts(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


async def apply_session_params(
    conn: asyncpg.Connection,
    window_start: datetime,
    window_end: datetime,
    source: str | None,
) -> None:
    """Set portfolio_kpi.* session params (same keys as DBeaver PARAMS block)."""
    await conn.execute(
        """
        SELECT
          set_config('portfolio_kpi.window_start', $1, false),
          set_config('portfolio_kpi.window_end', $2, false),
          set_config('portfolio_kpi.source_filter', $3, false)
        """,
        _format_ts(window_start),
        _format_ts(window_end),
        source or "",
    )


def load_sql_reports(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise SystemExit(f"SQL file not found: {path}")
    text = path.read_text(encoding="utf-8")
    matches = list(REPORT_HEADER.finditer(text))
    if not matches:
        raise SystemExit(f"No -- REPORT: markers found in {path}")

    reports: dict[str, str] = {}
    for i, match in enumerate(matches):
        name = match.group(1)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if not body.endswith(";"):
            body = body.rstrip() + ";"
        reports[name] = body
    return reports


def parse_timestamp(value: str, label: str) -> datetime:
    raw = value.strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise SystemExit(
        f"Invalid {label} {value!r}. Use e.g. 2026-05-20 00:00:00 or 2026-05-20."
    )


def resolve_reports(report_arg: str) -> list[str]:
    if report_arg == "all":
        return list(ALL_REPORT_KEYS)
    key = REPORT_ALIASES.get(report_arg)
    if key is None:
        raise SystemExit(
            f"Unknown --report {report_arg!r}. Choose: {', '.join(REPORT_CHOICES)}"
        )
    return [key]


def rows_to_dicts(rows: list[asyncpg.Record]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        item: dict[str, Any] = {}
        for key in row.keys():
            val = row[key]
            if isinstance(val, datetime):
                item[key] = val.isoformat(sep=" ", timespec="seconds")
            else:
                item[key] = val
        out.append(item)
    return out


def print_table(rows: list[dict[str, Any]], title: str) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)
    if not rows:
        print("(no rows)")
        return
    columns = list(rows[0].keys())
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    header = " | ".join(c.ljust(widths[c]) for c in columns)
    print(header)
    print("-" * len(header))
    for row in rows:
        print(" | ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns))
    print(f"\n({len(rows)} row(s))")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


async def run_reports(
    settings: PostgresSettings,
    window_start: datetime,
    window_end: datetime,
    report_keys: list[str],
    source: str | None,
    export_csv: Path | None,
) -> int:
    if window_end <= window_start:
        raise SystemExit("--end must be after --start.")

    queries = load_sql_reports(SQL_FILE)
    missing = [k for k in report_keys if k not in queries]
    if missing:
        raise SystemExit(f"SQL file missing report(s): {', '.join(missing)}")

    conn = await asyncpg.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
        timeout=60,
    )
    try:
        await apply_session_params(conn, window_start, window_end, source)
        for report_key in report_keys:
            sql = queries[report_key]
            needs_source = report_key in ("slow_global", "slow_by_source")
            rows = await conn.fetch(sql)

            dict_rows = rows_to_dicts(list(rows))
            title = (
                f"{report_key}  |  window [{window_start}] .. [{window_end})"
                + (f"  |  source={source!r}" if needs_source and source else "")
            )
            print_table(dict_rows, title)

            if export_csv is not None:
                stem = export_csv.stem
                suffix = export_csv.suffix or ".csv"
                out = export_csv.parent / f"{stem}_{report_key}{suffix}"
                write_csv(out, dict_rows)
                print(f"Wrote {out.resolve()}")
    finally:
        await conn.close()

    return 0


def main() -> None:
    _load_dotenv_from_project_root()
    parser = argparse.ArgumentParser(
        description="Portfolio KPI update log metrics (hourly volume, slow messages).",
    )
    parser.add_argument(
        "--start",
        required=True,
        metavar="TIMESTAMP",
        help='Window start (inclusive), e.g. "2026-05-20 00:00:00".',
    )
    parser.add_argument(
        "--end",
        required=True,
        metavar="TIMESTAMP",
        help='Window end (exclusive), e.g. "2026-05-21 00:00:00".',
    )
    parser.add_argument(
        "--report",
        required=True,
        choices=REPORT_CHOICES,
        help=(
            "hourly: received vs processed per hour; "
            "hourly_by_status: same by status; "
            "status: counts by status; "
            "slow: above global P95 process time; "
            "slow_by_source: above per-source P95; "
            "all: run every report."
        ),
    )
    parser.add_argument(
        "--source",
        default=None,
        metavar="NAME",
        help='Filter slow reports to entity_refresh_message->>"source" (e.g. Custom Financials).',
    )
    parser.add_argument(
        "--export-csv",
        type=Path,
        default=None,
        metavar="PATH",
        help="Write each report to CSV (filename gets _<report> suffix). Relative paths go under output/portfolio_kpi_metrics/.",
    )
    args = parser.parse_args()

    window_start = parse_timestamp(args.start, "--start")
    window_end = parse_timestamp(args.end, "--end")
    source = (args.source or "").strip() or None
    report_keys = resolve_reports(args.report)

    export_path = args.export_csv
    if export_path is not None:
        export_path = resolve_cli_artifact(export_path, "portfolio_kpi_metrics")

    settings = PostgresSettings.from_env()

    try:
        code = asyncio.run(
            run_reports(
                settings,
                window_start,
                window_end,
                report_keys,
                source,
                export_path,
            )
        )
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        code = 130
    raise SystemExit(code)


if __name__ == "__main__":
    main()
