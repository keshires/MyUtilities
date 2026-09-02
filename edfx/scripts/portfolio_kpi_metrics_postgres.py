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
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))
from project_paths import PROJECT_ROOT, resolve_cli_artifact

try:
    import asyncpg
except ImportError as exc:  # pragma: no cover
    raise SystemExit("asyncpg is required. Install with: pip install asyncpg") from exc

from run_portfolio_kpis_postgres import PostgresSettings


def load_env(env: str | None, root: Path = PROJECT_ROOT) -> list[Path]:
    """Load .env.<env> then base .env (override=False → OS env > env-file > base).

    Missing .env.<env> is a warning, not an error. Returns the files loaded.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return []
    loaded: list[Path] = []
    if env:
        env_path = root / f".env.{env}"
        if env_path.is_file():
            load_dotenv(env_path, override=False)
            loaded.append(env_path)
        else:
            print(
                f"warning: --env {env} given but {env_path} not found; "
                "falling back to base .env / OS environment.",
                file=sys.stderr,
            )
    base_path = root / ".env"
    if base_path.is_file():
        load_dotenv(base_path, override=False)
        loaded.append(base_path)
    return loaded


SQL_FILE = PROJECT_ROOT / "Docs" / "portfolio-kpi-metrics.sql"
SECTION_HEADER = re.compile(r"^--\s*(REPORT|SETUP):\s*(\w+)\s*$", re.MULTILINE)

REPORT_ALIASES: dict[str, str] = {
    "hourly": "hourly_totals",
    "hourly_by_status": "hourly_by_status",
    "status": "status_summary",
    "slow": "slow_global",
    "slow_by_source": "slow_by_source",
    "source_update_totals": "source_update_totals",
    "entity_counts": "triggering_entity_counts",
    "entities_by_day": "triggering_entity_counts_by_day",
    "portfolio_updates_by_source": "portfolio_updates_by_source",
    "daily": "daily_totals_source",
    "entity_source_totals": "entity_source_totals",
    "portfolio_update_totals": "portfolio_update_totals",
    "entities_by_day_source_status": "entities_by_day_source_status",
    "portfolios_by_day_source_status": "portfolios_by_day_source_status",
    "entity_by_source": "entity_by_source",
    "portfolio_entity_source": "portfolio_entity_source",
}

REPORT_CHOICES = tuple(REPORT_ALIASES.keys()) + ("all",)

# `all` is aggregate-only: per-source entity_source_totals, NOT per-entity triggering_entity_counts.
ALL_REPORT_KEYS = (
    "daily_totals_source",
    "hourly_totals",
    "hourly_by_status",
    "status_summary",
    "source_update_totals",
    "entity_source_totals",
    "triggering_entity_counts_by_day",
    "entities_by_day_source_status",
    "portfolios_by_day_source_status",
)

# marker -> (index_cols, pivot_col, value_col) for Python-side pivots.
PIVOT_SPECS: dict[str, tuple[list[str], str, str]] = {
    "entity_by_source": (["entity_id"], "source", "refresh_count"),
    "portfolio_entity_source": (["portfolio_id", "entity_id"], "source", "refresh_count"),
}


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


def load_sql_sections(text: str) -> tuple[str, dict[str, str]]:
    """Split a report SQL file into (setup_sql, {report_name: body}).

    Sections are delimited by ``-- SETUP: <name>`` and ``-- REPORT: <name>``
    header lines. SETUP bodies are concatenated verbatim; REPORT bodies are
    each ensured to end with ';'.
    """
    matches = list(SECTION_HEADER.finditer(text))
    setup_parts: list[str] = []
    reports: dict[str, str] = {}
    for i, match in enumerate(matches):
        kind = match.group(1)
        name = match.group(2)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if kind == "SETUP":
            if body:
                setup_parts.append(body)
        else:  # REPORT
            if not body.endswith(";"):
                body = body.rstrip() + ";"
            reports[name] = body
    if not reports:
        raise SystemExit("No -- REPORT: markers found in SQL file")
    return "\n\n".join(setup_parts), reports


def load_sql_file_sections(path: Path) -> tuple[str, dict[str, str]]:
    """Read a SQL file from disk and split it into (setup_sql, reports)."""
    if not path.is_file():
        raise SystemExit(f"SQL file not found: {path}")
    return load_sql_sections(path.read_text(encoding="utf-8"))


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


def is_pivot(report_key: str) -> bool:
    return report_key in PIVOT_SPECS


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


def pivot_rows(
    rows: list[dict[str, Any]],
    index_cols: list[str],
    pivot_col: str,
    value_col: str,
    top: int | None = None,
) -> list[dict[str, Any]]:
    """Pivot long-form rows to wide: one column per distinct pivot value.

    Columns are ordered: index_cols, then distinct pivot values sorted
    ascending, then 'total'. Rows are sorted by total DESC then index cols ASC,
    and truncated to `top` rows when given.
    """
    if not rows:
        return []

    sources = sorted({str(r[pivot_col]) for r in rows})

    aggregated: dict[tuple, dict[str, int]] = {}
    for r in rows:
        key = tuple(r[c] for c in index_cols)
        bucket = aggregated.setdefault(key, {})
        src = str(r[pivot_col])
        bucket[src] = bucket.get(src, 0) + int(r[value_col] or 0)

    wide: list[dict[str, Any]] = []
    for key, bucket in aggregated.items():
        row: dict[str, Any] = {c: key[i] for i, c in enumerate(index_cols)}
        total = 0
        for src in sources:
            val = int(bucket.get(src, 0))
            row[src] = val
            total += val
        row["total"] = total
        wide.append(row)

    # Stable two-pass sort: index cols ascending in NATURAL order (each column is
    # homogeneously typed, so int columns sort numerically), then total descending.
    wide.sort(key=lambda row: tuple(row[c] for c in index_cols))
    wide.sort(key=lambda row: row["total"], reverse=True)
    if top is not None:
        wide = wide[:top]
    return wide


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
    top: int | None,
) -> int:
    if window_end <= window_start:
        raise SystemExit("--end must be after --start.")

    setup_sql, queries = load_sql_file_sections(SQL_FILE)
    missing = [k for k in report_keys if k not in queries]
    if missing:
        raise SystemExit(f"SQL file missing report(s): {', '.join(missing)}")
    if not setup_sql:
        raise SystemExit("SQL file has no -- SETUP: build_temp block.")

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
        # Build the temp tables ONCE for this run.
        await conn.execute(setup_sql)

        for report_key in report_keys:
            sql = queries[report_key]
            rows = await conn.fetch(sql)
            dict_rows = rows_to_dicts(list(rows))

            # For pivots: build the full wide table (top=None) — CSV always gets
            # every row; only the stdout view is capped to --top.
            if is_pivot(report_key):
                index_cols, pivot_col, value_col = PIVOT_SPECS[report_key]
                csv_rows = pivot_rows(dict_rows, index_cols, pivot_col, value_col, top=None)
                display_rows = csv_rows[:top] if top is not None else csv_rows
            else:
                csv_rows = dict_rows
                display_rows = dict_rows

            title = f"{report_key}  |  window [{window_start}] .. [{window_end})"
            if source:
                title += f"  |  source={source!r}"
            if is_pivot(report_key) and top is not None:
                title += f"  |  top={top} of {len(csv_rows)}"
            print_table(display_rows, title)

            if export_csv is not None:
                stem = export_csv.stem
                suffix = export_csv.suffix or ".csv"
                out = export_csv.parent / f"{stem}_{report_key}{suffix}"
                write_csv(out, csv_rows)
                print(f"Wrote {out.resolve()}")
    finally:
        await conn.close()

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Portfolio KPI update log metrics (optimized temp-table reports).",
    )
    parser.add_argument("--start", required=True, metavar="TIMESTAMP",
                        help='Window start (inclusive), e.g. "2026-05-20 00:00:00".')
    parser.add_argument("--end", required=True, metavar="TIMESTAMP",
                        help='Window end (exclusive), e.g. "2026-05-21 00:00:00".')
    parser.add_argument("--report", required=True, choices=REPORT_CHOICES,
                        help="Report to run (see --help for the full list). 'all' runs the aggregate set.")
    parser.add_argument("--source", default=None, metavar="NAME",
                        help="Scope the whole run to entity_refresh_message->>'source' (e.g. 'Custom Financials').")
    parser.add_argument("--env", default=os.getenv("KPI_ENV"), metavar="NAME",
                        help="Environment: loads .env.<env> ahead of base .env (e.g. ci, qa, stg, prod).")
    parser.add_argument("--top", type=int, default=None, metavar="N",
                        help="For pivot reports (entity_by_source, portfolio_entity_source): cap rows printed to stdout (CSV keeps all).")
    parser.add_argument("--export-csv", type=Path, default=None, metavar="PATH",
                        help="Write each report to CSV (filename gets _<report> suffix). Relative paths go under output/portfolio_kpi_metrics/.")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    load_env(args.env)

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
                settings, window_start, window_end,
                report_keys, source, export_path, args.top,
            )
        )
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        code = 130
    raise SystemExit(code)


if __name__ == "__main__":
    main()
