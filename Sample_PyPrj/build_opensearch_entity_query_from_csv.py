"""
Build an OpenSearch _search body from a bulk-upload CSV.

**Source column (both outputs):** ``companyIdentifier`` (case-insensitive header)
is **required**. It feeds OpenSearch **and** the API ``queries`` payload; values
are deduplicated (first-seen order).

OpenSearch ``terms`` use the index field ``customEntityIdentifier.keyword``; the
**values** are your ``companyIdentifier`` strings. The payload JSON keys stay
``entityId`` and ``customEntityIdentifier`` as required by the API, with those
same string values.

Repeated ``companyIdentifier`` values across rows are **collapsed to a single
entry** in the ``terms`` array (first row wins for ordering; comparison is
case-sensitive after strip). The ``terms`` list length is the number of
**distinct** ids in that column, not the row count of the CSV.

The ``{"queries": [...]}`` payload lists each **unique** id as
``{"entityId": "<id>"}`` then ``{"customEntityIdentifier": "<id>"}``, with
``<id>`` from ``companyIdentifier``.

Each queries file allows at most **100 entities** (200 ``queries`` objects). If
there are more unique ids, multiple JSON files are written: ``queries_1.json``,
``queries_2.json``, … beside the path you pass to ``--queries-out`` (e.g.
``queries.json`` → ``queries_1.json``). A single file uses the exact
``--queries-out`` path when everything fits in one chunk.

**``--output-dir`` writes:**

- ``opensearch_search_full.json`` — one search body with **all** distinct ids in
  ``terms`` and ``size`` set to retrieve up to that many hits (capped by
  ``--opensearch-result-cap``, default 10000).
- ``opensearch_search_100.json`` or ``opensearch_search_100_1.json``, … — same
  query shape but **at most 100** ids per file in ``terms`` (uses the same chunk
  size as ``--queries-entities-per-file``, default 100).
- ``queries_payload.json`` / ``queries_payload_1.json``, … — API payload chunks.

Or pass both ``--out`` and ``--queries-out`` with different paths (single OpenSearch
file uses ``--size`` as today).

Example (single directory, two artifacts; relative ``--output-dir`` → ``output/opensearch_queries/``):
  python build_opensearch_entity_query_from_csv.py ^
    --tenant-id <your-tenant-id> ^
    --csv "C:\\Github\\Sample_PyPrj\\BulkUplaodFiles\\your_file.csv" ^
    --output-dir my_export_run

Example (explicit paths; relative ``--out`` / ``--queries-out`` → ``output/opensearch_queries/``):
  python build_opensearch_entity_query_from_csv.py ^
    --csv "...\\data.csv" ^
    --out opensearch_search.json ^
    --queries-out queries_payload.json

If ``--csv`` is omitted, the newest ``*.csv`` under ``BulkUplaodFiles`` next to
this script is used (folder name matches your path: BulkUplaodFiles).

Distinct count only (no JSON written)::

  python build_opensearch_entity_query_from_csv.py --distinct-count --csv "...\\data.csv"
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from project_paths import resolve_cli_artifact

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

DEFAULT_BULK_DIR = Path(__file__).resolve().parent / "BulkUplaodFiles"
DEFAULT_QUERIES_ENTITIES_PER_FILE = 100
DEFAULT_OPENSEARCH_RESULT_CAP = 10_000
OPENSEARCH_FULL_FILENAME = "opensearch_search_full.json"
OPENSEARCH_TERMS_CHUNK_BASENAME = "opensearch_search_100.json"
QUERIES_PAYLOAD_FILENAME = "queries_payload.json"

_SOURCE_FIELDS = [
    "customEntityIdentifier",
    "entityContactCountryCode",
    "entityCountryName",
    "entityInternationalName",
    "isCustom",
    "nationalId",
    "primaryIndustryNDYDescription",
    "tenantId",
    "identifierBvd",
    "entityId",
]


def _find_column(fieldnames: list[str] | None, header_lower: str) -> str | None:
    if not fieldnames:
        return None
    want = header_lower.strip().lower()
    for name in fieldnames:
        if name and name.strip().lower() == want:
            return name
    return None


def unique_ordered(identifiers: Sequence[str]) -> list[str]:
    """Unique values in first-seen order (case-sensitive; callers may pre-strip)."""
    return list(dict.fromkeys(identifiers))


def load_company_identifiers(csv_path: Path) -> tuple[list[str], str, int, int]:
    """
    Read ``companyIdentifier`` (required). Returns unique ordered values, the
    header name used, non-empty cell count, and total data row count.
    """
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise ValueError("CSV has no header row.")
        col = _find_column(fieldnames, "companyidentifier")
        if not col:
            raise ValueError(
                "CSV must include a 'companyIdentifier' column. "
                f"Headers: {list(fieldnames)}"
            )
        raw_order: list[str] = []
        data_rows = 0
        for row in reader:
            data_rows += 1
            raw = row.get(col)
            if raw is None:
                continue
            v = str(raw).strip()
            if v:
                raw_order.append(v)
    out = unique_ordered(raw_order)
    if not out:
        raise ValueError(f"No non-empty values in column {col!r} ({csv_path}).")
    non_empty = len(raw_order)
    return out, col, non_empty, data_rows


def pick_latest_csv(directory: Path) -> Path:
    if not directory.is_dir():
        raise FileNotFoundError(
            f"Bulk CSV directory not found: {directory}. "
            "Create it or pass --csv explicitly."
        )
    candidates = sorted(
        directory.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not candidates:
        raise FileNotFoundError(f"No *.csv files under {directory}.")
    return candidates[0]


def search_result_size(num_terms: int, cap: int) -> int:
    """``size`` for _search: at least one, at most ``cap`` (OpenSearch/ES safe default)."""
    if cap < 1:
        raise ValueError("cap must be >= 1")
    return min(max(num_terms, 1), cap)


def build_search_body(identifiers: list[str], tenant_id: str, size: int) -> dict:
    unique_ids = unique_ordered(identifiers)
    terms_clause = {"terms": {"customEntityIdentifier.keyword": unique_ids}}
    return {
        "_source": _SOURCE_FIELDS,
        "size": size,
        "query": {
            "bool": {
                "should": [
                    {
                        "bool": {
                            "should": [
                                {
                                    "bool": {
                                        "must": [
                                            terms_clause,
                                            {"term": {"_index": "entity"}},
                                        ]
                                    }
                                },
                                {
                                    "bool": {
                                        "must": [
                                            terms_clause,
                                            {"term": {"_index": "custom-entity"}},
                                            {"term": {"tenantId.keyword": tenant_id}},
                                        ]
                                    }
                                },
                            ]
                        }
                    }
                ]
            }
        },
    }


def build_queries_payload(
    identifiers: Sequence[str],
) -> dict[str, list[dict[str, str]]]:
    """For each unique ``companyIdentifier`` value: entityId then customEntityIdentifier keys."""
    unique_ids = unique_ordered(identifiers)
    queries: list[dict[str, str]] = []
    for uid in unique_ids:
        queries.append({"entityId": uid})
        queries.append({"customEntityIdentifier": uid})
    return {"queries": queries}


def chunk_identifiers(identifiers: Sequence[str], chunk_size: int) -> list[list[str]]:
    """Split ordered unique ids into chunks of at most ``chunk_size`` entities each."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    ids = list(identifiers)
    return [ids[i : i + chunk_size] for i in range(0, len(ids), chunk_size)]


def write_opensearch_full_file(
    path: Path,
    ids: list[str],
    tenant_id: str,
    result_cap: int,
) -> None:
    """Single OpenSearch body listing every distinct id in ``terms``."""
    sz = search_result_size(len(ids), result_cap)
    body = build_search_body(ids, tenant_id, sz)
    path.write_text(json.dumps(body, indent=4), encoding="utf-8")


def write_opensearch_terms_chunk_files(
    out_dir: Path,
    ids: list[str],
    tenant_id: str,
    terms_per_file: int,
    result_cap: int,
) -> list[Path]:
    """One JSON per chunk: at most ``terms_per_file`` ids in ``terms`` each."""
    chunks = chunk_identifiers(ids, terms_per_file)
    base = out_dir / OPENSEARCH_TERMS_CHUNK_BASENAME
    paths = queries_output_paths(base, len(chunks))
    for path, chunk in zip(paths, chunks):
        sz = search_result_size(len(chunk), result_cap)
        body = build_search_body(chunk, tenant_id, sz)
        path.write_text(json.dumps(body, indent=4), encoding="utf-8")
    return paths


def write_queries_chunk_files(
    base_path: Path,
    query_ids: list[str],
    entities_per_file: int,
) -> list[Path]:
    """Write one or more ``{"queries": [...]}`` files; return paths written."""
    chunks = chunk_identifiers(query_ids, entities_per_file)
    paths = queries_output_paths(base_path, len(chunks))
    for path, chunk in zip(paths, chunks):
        payload = build_queries_payload(chunk)
        path.write_text(json.dumps(payload, indent=4), encoding="utf-8")
    return paths


def queries_output_paths(base_path: Path, num_chunks: int) -> list[Path]:
    """
    If one chunk, use ``base_path`` exactly. If several, use ``{stem}_{n}{suffix}``
    (1-based n) in the same directory — e.g. ``out/queries.json`` → ``out/queries_1.json``.
    """
    if num_chunks < 1:
        raise ValueError("num_chunks must be >= 1")
    if num_chunks == 1:
        return [base_path]
    parent = base_path.parent
    stem = base_path.stem
    suffix = base_path.suffix
    return [parent / f"{stem}_{i}{suffix}" for i in range(1, num_chunks + 1)]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Path to CSV. Default: newest *.csv under BulkUplaodFiles beside this script.",
    )
    p.add_argument(
        "--tenant-id",
        default=os.getenv("OPENSEARCH_TENANT_ID", "0014000000NY0RK"),
        help=(
            "Value for tenantId.keyword in the custom-entity branch. "
            "Override with OPENSEARCH_TENANT_ID in .env (default matches legacy sample)."
        ),
    )
    p.add_argument("--size", type=int, default=10, help="Search size (default: 10).")
    p.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            f"Write {OPENSEARCH_FULL_FILENAME!r} (all ids), "
            f"{OPENSEARCH_TERMS_CHUNK_BASENAME!r} chunk(s) (max ids per file = --queries-entities-per-file), "
            f"and {QUERIES_PAYLOAD_FILENAME!r} payload chunk(s). Do not combine with --out or --queries-out. "
            "Relative paths are placed under output/opensearch_queries/ at the project root."
        ),
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Write OpenSearch _search JSON only to this path (separate from --queries-out). "
            "Relative paths go under output/opensearch_queries/."
        ),
    )
    p.add_argument(
        "--queries-out",
        type=Path,
        default=None,
        help=(
            'Write {"queries": [...]} payload only (max 100 entities per file; '
            "chunked as stem_1.json, …). Use with --out for two explicit files, or use --output-dir. "
            "Relative paths go under output/opensearch_queries/."
        ),
    )
    p.add_argument(
        "--queries-entities-per-file",
        type=int,
        default=DEFAULT_QUERIES_ENTITIES_PER_FILE,
        metavar="N",
        help=f"Max unique entities per queries JSON file (default: {DEFAULT_QUERIES_ENTITIES_PER_FILE}).",
    )
    p.add_argument(
        "--distinct-count",
        action="store_true",
        help="Print distinct companyIdentifier count and row stats to stdout; do not write OpenSearch/payload files.",
    )
    p.add_argument(
        "--opensearch-result-cap",
        type=int,
        default=DEFAULT_OPENSEARCH_RESULT_CAP,
        metavar="N",
        help=(
            "Max ``size`` in generated OpenSearch bodies under --output-dir "
            f"(default: {DEFAULT_OPENSEARCH_RESULT_CAP})."
        ),
    )
    return p.parse_args(argv)


def _validate_output_args(args: argparse.Namespace) -> str | None:
    """Return error message, or None if OK."""
    if args.output_dir and (args.out or args.queries_out):
        return "Use either --output-dir alone, or --out / --queries-out (do not combine with --output-dir)."
    if args.distinct_count and (args.output_dir or args.out or args.queries_out):
        return "--distinct-count cannot be combined with --output-dir, --out, or --queries-out."
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    err = _validate_output_args(args)
    if err:
        print(err, file=sys.stderr)
        return 2

    if args.output_dir is not None:
        args.output_dir = resolve_cli_artifact(args.output_dir, "opensearch_queries")
    if args.out is not None:
        args.out = resolve_cli_artifact(args.out, "opensearch_queries")
    if args.queries_out is not None:
        args.queries_out = resolve_cli_artifact(args.queries_out, "opensearch_queries")

    csv_path = args.csv.expanduser() if args.csv else pick_latest_csv(DEFAULT_BULK_DIR)
    if not csv_path.is_file():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        return 1

    if args.distinct_count:
        ids, id_col, non_empty, data_rows = load_company_identifiers(csv_path)
        print(f"column: {id_col}")
        print(f"distinct_companyIdentifier: {len(ids)}")
        print(f"non_empty_cells_in_column: {non_empty}")
        print(f"data_rows_in_csv: {data_rows}")
        print(f"csv_path: {csv_path}")
        return 0

    cap = args.opensearch_result_cap
    if cap < 1:
        print("--opensearch-result-cap must be >= 1", file=sys.stderr)
        return 1

    per = args.queries_entities_per_file
    if per < 1:
        print("--queries-entities-per-file must be >= 1", file=sys.stderr)
        return 1

    ids, id_col, non_empty, data_rows = load_company_identifiers(csv_path)
    body = build_search_body(ids, args.tenant_id.strip(), args.size)
    search_text = json.dumps(body, indent=4)
    print(
        f"OpenSearch + queries source: {len(ids)} unique id(s) from column {id_col!r} "
        f"({non_empty} non-empty cell(s) across {data_rows} data row(s) in {csv_path}).",
        file=sys.stderr,
    )

    if args.output_dir:
        out_dir = args.output_dir.expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        tenant = args.tenant_id.strip()
        full_path = out_dir / OPENSEARCH_FULL_FILENAME
        write_opensearch_full_file(full_path, ids, tenant, cap)
        os_paths = write_opensearch_terms_chunk_files(out_dir, ids, tenant, per, cap)
        queries_base = out_dir / QUERIES_PAYLOAD_FILENAME
        q_paths = write_queries_chunk_files(queries_base, ids, per)
        print(
            f"Wrote OpenSearch (full, all {len(ids)} ids): {full_path}", file=sys.stderr
        )
        if len(os_paths) > 1:
            print(
                f"Wrote {len(os_paths)} OpenSearch term-chunk files ({per} ids max each; "
                f"last may be shorter): {', '.join(str(p) for p in os_paths)}",
                file=sys.stderr,
            )
        else:
            print(f"Wrote OpenSearch term-chunk file: {os_paths[0]}", file=sys.stderr)
        if len(q_paths) > 1:
            print(
                f"Wrote {len(q_paths)} payload files ({per} entities max each; "
                f"last may be shorter): {', '.join(str(p) for p in q_paths)}",
                file=sys.stderr,
            )
        else:
            print(f"Wrote payload: {q_paths[0]}", file=sys.stderr)
        return 0

    if args.out:
        args.out.expanduser().write_text(search_text, encoding="utf-8")
    else:
        print(search_text)

    if args.queries_out:
        out_base = args.queries_out.expanduser()
        paths = write_queries_chunk_files(out_base, ids, per)
        if len(paths) > 1:
            listed = ", ".join(str(p) for p in paths)
            print(
                f"Wrote {len(paths)} queries files ({per} entities max each; "
                f"last file may be shorter): {listed}",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
