"""
Refresh stale non-public entities via Tessera UI API.

Supports two entity modes (``--entity-type``):

**custom** — Custom entities (``custom_id IS NOT NULL``)::

    SELECT DISTINCT external_id FROM public.entity
    WHERE data_type = 'Private' AND custom_id IS NOT NULL ...

    Payload: ``{"type": "non-public-customized", "force": true, "entities": [...]}``

**private** — Private entities (``custom_id IS NULL``)::

    SELECT DISTINCT external_id FROM public.entity
    WHERE data_type = 'Private' AND custom_id IS NULL ...

    Payload: ``{"type": "non-public", "force": true, "entities": [...]}``

Both queries exclude tenant ``0014000000NXtS8`` and use ``updated_date <`` first of
current month (override with ``--date-filter``).

Monthly run:
  python refresh_stale_non_public_entities.py --entity-type custom --dry-run
  python refresh_stale_non_public_entities.py --entity-type private --dry-run
  python refresh_stale_non_public_entities.py --entity-type custom
  python refresh_stale_non_public_entities.py --entity-type private --workers 3
  python refresh_stale_non_public_entities.py --entity-type private --resume-from-batch 44
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
import threading
import time
from collections.abc import AsyncIterator
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import asyncpg
import requests
import urllib3
from dotenv import load_dotenv

from project_paths import logs_dir

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_TESSERA_BASE_URL = "https://api.edfx.moodysanalytics.com"
DEFAULT_SSO_URL = "https://sso.moodysanalytics.com/sso-api/v1/token"
DEFAULT_EXCLUDED_TENANTS = ("0014000000NXtS8",)
DEFAULT_BATCH_SIZE = 15000
DEFAULT_WORKERS = 3
TOKEN_MAX_AGE_SECONDS = 600  # 10 minutes
REQUEST_TIMEOUT = 120
SHOW_PROGRESS_EVERY = 10
CURSOR_PREFETCH = 60000

POSTGRES_ENV_KEYS = (
    "TESSERA_POSTGRES_HOST",
    "TESSERA_POSTGRES_DB",
    "TESSERA_POSTGRES_USER",
    "TESSERA_POSTGRES_PASSWORD",
)

STALE_ENTITIES_QUERY_BASE = """
SELECT DISTINCT external_id
FROM public.entity
WHERE data_type = 'Private'
  AND {custom_id_clause}
  AND external_id IS NOT NULL
  AND {tenant_clause}
  {date_clause}
ORDER BY external_id
"""

STALE_ENTITIES_COUNT_QUERY_BASE = """
SELECT COUNT(DISTINCT external_id)
FROM public.entity
WHERE data_type = 'Private'
  AND {custom_id_clause}
  AND external_id IS NOT NULL
  AND {tenant_clause}
  {date_clause}
"""

DATE_CLAUSE_STALE = """AND (
        updated_date IS NULL
        OR updated_date < $1::timestamp
      )"""
DATE_CLAUSE_ALL = ""

TENANT_CLAUSE_EXCLUDE = "tenant_id <> ALL($2::text[])"
TENANT_CLAUSE_INCLUDE = "tenant_id = $2::text"
TENANT_CLAUSE_EXCLUDE_ALL = "tenant_id <> ALL($1::text[])"
TENANT_CLAUSE_INCLUDE_ALL = "tenant_id = $1::text"


@dataclass(frozen=True)
class EntityRefreshMode:
    name: str
    payload_type: str
    custom_id_clause: str
    description: str


ENTITY_MODES: dict[str, EntityRefreshMode] = {
    "custom": EntityRefreshMode(
        name="custom",
        payload_type="non-public-customized",
        custom_id_clause="custom_id IS NOT NULL",
        description="Custom entities (custom_id IS NOT NULL)",
    ),
    "private": EntityRefreshMode(
        name="private",
        payload_type="non-public",
        custom_id_clause="custom_id IS NULL",
        description="Private entities (custom_id IS NULL)",
    ),
}


def resolve_entity_mode(raw: str) -> EntityRefreshMode:
    key = (raw or "").strip().lower()
    aliases = {"customized": "custom", "customised": "custom"}
    key = aliases.get(key, key)
    if key not in ENTITY_MODES:
        valid = ", ".join(sorted(ENTITY_MODES))
        raise SystemExit(f"Invalid --entity-type {raw!r}. Choose one of: {valid}")
    return ENTITY_MODES[key]


def tenant_clause(*, tenant_id: str | None, include_all: bool = False) -> str:
    if tenant_id:
        return TENANT_CLAUSE_INCLUDE_ALL if include_all else TENANT_CLAUSE_INCLUDE
    return TENANT_CLAUSE_EXCLUDE_ALL if include_all else TENANT_CLAUSE_EXCLUDE


def stale_entities_query(
    mode: EntityRefreshMode, *, tenant_id: str | None = None, include_all: bool = False
) -> str:
    return STALE_ENTITIES_QUERY_BASE.format(
        custom_id_clause=mode.custom_id_clause,
        tenant_clause=tenant_clause(tenant_id=tenant_id, include_all=include_all),
        date_clause=DATE_CLAUSE_ALL if include_all else DATE_CLAUSE_STALE,
    )


def stale_entities_count_query(
    mode: EntityRefreshMode, *, tenant_id: str | None = None, include_all: bool = False
) -> str:
    return STALE_ENTITIES_COUNT_QUERY_BASE.format(
        custom_id_clause=mode.custom_id_clause,
        tenant_clause=tenant_clause(tenant_id=tenant_id, include_all=include_all),
        date_clause=DATE_CLAUSE_ALL if include_all else DATE_CLAUSE_STALE,
    )


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def tessera_base_url() -> str:
    return (
        _env("TESSERA_BASE_URL")
        or _env("TESSEARA_BASE_URL")
        or DEFAULT_TESSERA_BASE_URL
    ).rstrip("/")


def excluded_tenant_ids() -> list[str]:
    raw = _env("STALE_REFRESH_EXCLUDED_TENANTS")
    if raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    return list(DEFAULT_EXCLUDED_TENANTS)


def first_of_current_month() -> date:
    today = date.today()
    return today.replace(day=1)


def missing_postgres_env() -> list[str]:
    return [key for key in POSTGRES_ENV_KEYS if not _env(key)]


def setup_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("refresh_stale_entities")
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


class TokenManager:
    """Thread-safe SSO bearer token cache with periodic refresh."""

    def __init__(
        self,
        *,
        sso_url: str,
        username: str,
        password: str,
        max_age_seconds: int,
        logger: logging.Logger,
        manual_token: str | None = None,
    ) -> None:
        self.sso_url = sso_url
        self.username = username
        self.password = password
        self.max_age_seconds = max_age_seconds
        self.logger = logger
        self.manual_token = manual_token
        self._token: str | None = manual_token
        self._obtained_at: float | None = None
        self._lock = threading.Lock()

    def _fetch_token(self) -> str:
        if not self.username or not self.password:
            raise RuntimeError(
                "Set MOODYS_SSO_USERNAME and MOODYS_SSO_PASSWORD in .env "
                "(or STALE_REFRESH_MANUAL_TOKEN)."
            )

        payload = {
            "username": self.username,
            "password": self.password,
            "grant_type": "password",
            "scope": "openid",
        }
        self.logger.info("Requesting SSO token from %s", self.sso_url)
        response = requests.post(
            self.sso_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=payload,
            verify=False,
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"SSO authentication failed: HTTP {response.status_code} — {response.text[:500]}"
            )

        token_data = response.json()
        token = token_data.get("id_token") or token_data.get("access_token")
        if not token:
            raise RuntimeError("SSO response did not include id_token or access_token")
        self.logger.info("SSO token acquired")
        return str(token)

    def _is_expired(self) -> bool:
        if self.manual_token:
            return False
        if not self._token or self._obtained_at is None:
            return True
        return (time.monotonic() - self._obtained_at) >= self.max_age_seconds

    def get_token(self, *, force_refresh: bool = False) -> str:
        with self._lock:
            if self.manual_token and not force_refresh:
                return self.manual_token
            if force_refresh or self._is_expired():
                if force_refresh:
                    self.logger.info("Refreshing SSO token (forced)")
                else:
                    self.logger.info(
                        "Refreshing SSO token (older than %s seconds)",
                        self.max_age_seconds,
                    )
                self._token = self._fetch_token()
                self._obtained_at = time.monotonic()
            assert self._token is not None
            return self._token

    def invalidate(self) -> None:
        with self._lock:
            if self.manual_token:
                return
            self._token = None
            self._obtained_at = None


async def pg_connect() -> asyncpg.Connection:
    return await asyncpg.connect(
        host=os.environ["TESSERA_POSTGRES_HOST"],
        port=int(os.getenv("TESSERA_POSTGRES_PORT", "5432")),
        database=os.environ["TESSERA_POSTGRES_DB"],
        user=os.environ["TESSERA_POSTGRES_USER"],
        password=os.environ["TESSERA_POSTGRES_PASSWORD"],
        ssl="prefer",
    )


async def count_stale_external_ids(
    *,
    mode: EntityRefreshMode,
    date_filter: date,
    excluded_tenants: list[str],
    tenant_id: str | None,
    include_all: bool,
) -> int:
    conn = await pg_connect()
    try:
        tenant_param = tenant_id if tenant_id else excluded_tenants
        query = stale_entities_count_query(mode, tenant_id=tenant_id, include_all=include_all)
        if include_all:
            value = await conn.fetchval(query, tenant_param)
        else:
            value = await conn.fetchval(
                query,
                datetime.combine(date_filter, datetime.min.time()),
                tenant_param,
            )
        return int(value or 0)
    finally:
        await conn.close()


async def iter_stale_batches(
    *,
    mode: EntityRefreshMode,
    date_filter: date,
    excluded_tenants: list[str],
    tenant_id: str | None,
    include_all: bool,
    batch_size: int,
    limit: int | None,
    resume_from_batch: int,
) -> AsyncIterator[tuple[int, list[str], bool]]:
    """Stream entity ids from Postgres in submission-sized batches."""
    conn = await pg_connect()
    cutoff = datetime.combine(date_filter, datetime.min.time())
    tenant_param = tenant_id if tenant_id else excluded_tenants
    batch_num = 0
    current: list[str] = []
    seen = 0
    query = stale_entities_query(mode, tenant_id=tenant_id, include_all=include_all)

    try:
        async with conn.transaction():
            if include_all:
                cursor = conn.cursor(
                    query,
                    tenant_param,
                    prefetch=min(CURSOR_PREFETCH, max(batch_size * 4, batch_size)),
                )
            else:
                cursor = conn.cursor(
                    query,
                    cutoff,
                    tenant_param,
                    prefetch=min(CURSOR_PREFETCH, max(batch_size * 4, batch_size)),
                )
            async for row in cursor:
                external_id = row["external_id"]
                if external_id is None:
                    continue
                seen += 1
                current.append(str(external_id))
                if limit is not None and seen >= limit:
                    batch_num += 1
                    skipped = batch_num < resume_from_batch
                    yield batch_num, current, skipped
                    current = []
                    break
                if len(current) < batch_size:
                    continue

                batch_num += 1
                skipped = batch_num < resume_from_batch
                yield batch_num, current, skipped
                current = []

            if current:
                batch_num += 1
                skipped = batch_num < resume_from_batch
                yield batch_num, current, skipped
    finally:
        await conn.close()


def create_http_session(workers: int) -> requests.Session:
    session = requests.Session()
    pool_size = max(workers * 2, 4)
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=pool_size,
        pool_maxsize=pool_size,
        max_retries=0,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_worker_local = threading.local()


def _get_thread_session() -> requests.Session:
    if not hasattr(_worker_local, "session"):
        _worker_local.session = create_http_session(2)
    return _worker_local.session


def print_submission_plan(
    *,
    entity_mode: EntityRefreshMode,
    total_found: int,
    submit_count: int,
    batch_count: int,
    batch_size: int,
    dry_run: bool,
    limit: int | None,
    resume_from_batch: int,
    logger: logging.Logger,
) -> None:
    run_mode = "DRY RUN — no API submissions" if dry_run else "LIVE — will POST to refreshEntities"
    lines = [
        "",
        "=" * 60,
        "STALE ENTITY REFRESH PLAN",
        "=" * 60,
        f"  Entity type                       : {entity_mode.name} ({entity_mode.description})",
        f"  API payload type                  : {entity_mode.payload_type}",
        f"  Stale entities found in database : {total_found:,}",
        f"  Entities to submit for refresh   : {submit_count:,}",
        f"  Payload batches                  : {batch_count:,} (max {batch_size:,} per batch)",
        f"  Mode                             : {run_mode}",
    ]
    if resume_from_batch > 1:
        lines.append(f"  Resume from batch                : {resume_from_batch}")
    if limit is not None and submit_count < total_found:
        lines.append(f"  Note                             : --limit {limit} applied")
    lines.append("=" * 60)
    message = "\n".join(lines)
    print(message)
    logger.info(message.replace("\n", " | "))


def submit_count(total_found: int, limit: int | None) -> int:
    if limit is None:
        return total_found
    return min(total_found, limit)


def batch_count(entity_count: int, batch_size: int) -> int:
    if entity_count <= 0:
        return 0
    return math.ceil(entity_count / batch_size)


def build_payload(entities: list[str], payload_type: str) -> dict[str, object]:
    return {
        "type": payload_type,
        "force": True,
        "entities": entities,
    }


def submit_refresh_batch(
    *,
    session: requests.Session | None,
    token_manager: TokenManager,
    base_url: str,
    payload_type: str,
    entities: list[str],
    batch_num: int,
    total_batches: int,
    logger: logging.Logger,
    dry_run: bool,
    verbose: bool,
) -> tuple[int, bool, int, str]:
    url = f"{base_url}/tesseraui/v1/refreshEntities"
    payload = build_payload(entities, payload_type)

    if dry_run:
        if verbose:
            logger.info(
                "[DRY RUN] Batch %s/%s — would POST %s entities (type=%s)",
                batch_num,
                total_batches,
                len(entities),
                payload_type,
            )
        return batch_num, True, 0, "dry-run"

    for attempt in (1, 2):
        token = token_manager.get_token(force_refresh=(attempt == 2))
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if verbose:
            logger.info(
                "Submitting batch %s/%s (%s entities) attempt=%s",
                batch_num,
                total_batches,
                len(entities),
                attempt,
            )
        try:
            http = session if session is not None else _get_thread_session()
            response = http.post(
                url,
                headers=headers,
                json=payload,
                verify=False,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.error(
                "Batch %s/%s request failed: %s", batch_num, total_batches, exc
            )
            return batch_num, False, 0, str(exc)

        body_preview = (response.text or "")[:1000]
        if response.status_code == 401 and attempt == 1:
            logger.warning(
                "Batch %s/%s HTTP 401 — refreshing token and retrying",
                batch_num,
                total_batches,
            )
            token_manager.invalidate()
            continue

        ok = response.ok
        if ok:
            if verbose:
                logger.info(
                    "Batch %s/%s succeeded: HTTP %s — %s",
                    batch_num,
                    total_batches,
                    response.status_code,
                    body_preview,
                )
        else:
            logger.error(
                "Batch %s/%s failed: HTTP %s — %s",
                batch_num,
                total_batches,
                response.status_code,
                body_preview,
            )
        return batch_num, ok, response.status_code, body_preview

    return batch_num, False, 401, "Unauthorized after token refresh"


def log_progress(
    *,
    completed: int,
    total_batches: int,
    ok_count: int,
    fail_count: int,
    elapsed: float,
    logger: logging.Logger,
) -> None:
    rate = completed / elapsed if elapsed > 0 else 0.0
    remaining = total_batches - completed
    eta = remaining / rate if rate > 0 else 0.0
    logger.info(
        "Progress %s/%s batches (ok=%s failed=%s) — %.1f batches/min, ETA ~%.0fs",
        completed,
        total_batches,
        ok_count,
        fail_count,
        rate * 60,
        eta,
    )


async def process_batches(
    *,
    mode: EntityRefreshMode,
    date_filter: date,
    excluded_tenants: list[str],
    tenant_id: str | None,
    include_all: bool,
    batch_size: int,
    limit: int | None,
    resume_from_batch: int,
    total_batches: int,
    workers: int,
    dry_run: bool,
    session: requests.Session | None,
    token_manager: TokenManager,
    base_url: str,
    logger: logging.Logger,
) -> tuple[int, int, int, list[dict[str, object]]]:
    ok_count = 0
    fail_count = 0
    skipped_count = 0
    run_results: list[dict[str, object]] = []
    completed = 0
    submit_started = time.monotonic()

    if workers <= 1:
        async for batch_num, entities, skipped in iter_stale_batches(
            mode=mode,
            date_filter=date_filter,
            excluded_tenants=excluded_tenants,
            tenant_id=tenant_id,
            include_all=include_all,
            batch_size=batch_size,
            limit=limit,
            resume_from_batch=resume_from_batch,
        ):
            if skipped:
                skipped_count += 1
                continue

            verbose = dry_run or batch_num == 1 or batch_num == total_batches
            if not dry_run and batch_num % SHOW_PROGRESS_EVERY == 0:
                verbose = True

            batch_num, ok, status_code, detail = submit_refresh_batch(
                session=session,
                token_manager=token_manager,
                base_url=base_url,
                payload_type=mode.payload_type,
                entities=entities,
                batch_num=batch_num,
                total_batches=total_batches,
                logger=logger,
                dry_run=dry_run,
                verbose=verbose,
            )
            completed += 1
            if ok:
                ok_count += 1
            else:
                fail_count += 1
                run_results.append(
                    {
                        "batch": batch_num,
                        "entity_count": len(entities),
                        "success": ok,
                        "http_status": status_code,
                        "detail": detail,
                    }
                )
            if not dry_run and (
                completed % SHOW_PROGRESS_EVERY == 0 or completed == total_batches
            ):
                log_progress(
                    completed=completed,
                    total_batches=total_batches,
                    ok_count=ok_count,
                    fail_count=fail_count,
                    elapsed=time.monotonic() - submit_started,
                    logger=logger,
                )
        return ok_count, fail_count, skipped_count, run_results

    in_flight: dict[Future[tuple[int, bool, int, str]], tuple[int, int]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        async for batch_num, entities, skipped in iter_stale_batches(
            mode=mode,
            date_filter=date_filter,
            excluded_tenants=excluded_tenants,
            tenant_id=tenant_id,
            include_all=include_all,
            batch_size=batch_size,
            limit=limit,
            resume_from_batch=resume_from_batch,
        ):
            if skipped:
                skipped_count += 1
                continue

            if not dry_run and token_manager._is_expired():
                token_manager.get_token(force_refresh=True)

            future = executor.submit(
                submit_refresh_batch,
                session=None,
                token_manager=token_manager,
                base_url=base_url,
                payload_type=mode.payload_type,
                entities=entities,
                batch_num=batch_num,
                total_batches=total_batches,
                logger=logger,
                dry_run=dry_run,
                verbose=False,
            )
            in_flight[future] = (batch_num, len(entities))

            while len(in_flight) >= workers:
                ok_count, fail_count, completed, run_results = _consume_future(
                    in_flight=in_flight,
                    ok_count=ok_count,
                    fail_count=fail_count,
                    completed=completed,
                    total_batches=total_batches,
                    submit_started=submit_started,
                    run_results=run_results,
                    logger=logger,
                    dry_run=dry_run,
                )

        while in_flight:
            ok_count, fail_count, completed, run_results = _consume_future(
                in_flight=in_flight,
                ok_count=ok_count,
                fail_count=fail_count,
                completed=completed,
                total_batches=total_batches,
                submit_started=submit_started,
                run_results=run_results,
                logger=logger,
                dry_run=dry_run,
            )

    return ok_count, fail_count, skipped_count, run_results


def _consume_future(
    *,
    in_flight: dict[Future[tuple[int, bool, int, str]], tuple[int, int]],
    ok_count: int,
    fail_count: int,
    completed: int,
    total_batches: int,
    submit_started: float,
    run_results: list[dict[str, object]],
    logger: logging.Logger,
    dry_run: bool,
) -> tuple[int, int, int, list[dict[str, object]]]:
    future = next(as_completed(in_flight))
    batch_num, entity_count = in_flight.pop(future)
    batch_num, ok, status_code, detail = future.result()
    completed += 1
    if ok:
        ok_count += 1
    else:
        fail_count += 1
        run_results.append(
            {
                "batch": batch_num,
                "entity_count": entity_count,
                "success": ok,
                "http_status": status_code,
                "detail": detail,
            }
        )
    if not dry_run and (completed % SHOW_PROGRESS_EVERY == 0 or completed == total_batches):
        log_progress(
            completed=completed,
            total_batches=total_batches,
            ok_count=ok_count,
            fail_count=fail_count,
            elapsed=time.monotonic() - submit_started,
            logger=logger,
        )
    return ok_count, fail_count, completed, run_results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--entity-type",
        default=None,
        help=(
            "Entity mode: 'custom' (non-public-customized) or 'private' (non-public). "
            "Aliases: customized. Default: STALE_REFRESH_ENTITY_TYPE or 'private'."
        ),
    )
    parser.add_argument(
        "--date-filter",
        type=str,
        default=None,
        help="Stale cutoff date (YYYY-MM-DD). Default: first day of current month.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.getenv("STALE_REFRESH_BATCH_SIZE", str(DEFAULT_BATCH_SIZE))),
        help=f"Entities per API payload (default: {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on total entities (testing).",
    )
    parser.add_argument(
        "--resume-from-batch",
        type=int,
        default=1,
        help="Skip batches before this number (1-based). Use to resume a stopped run.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.getenv("STALE_REFRESH_WORKERS", str(DEFAULT_WORKERS))),
        help=(
            f"Parallel API submission workers (default: {DEFAULT_WORKERS}). "
            "Use 1 for sequential posts."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Query DB and log batches without calling refreshEntities.",
    )
    parser.add_argument(
        "--tenant-id",
        type=str,
        default=None,
        help="Restrict refresh to a single tenant_id (overrides tenant exclusion).",
    )
    parser.add_argument(
        "--all-entities",
        action="store_true",
        help="Include all matching entities, not only those stale by --date-filter.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    entity_type_raw = args.entity_type or _env("STALE_REFRESH_ENTITY_TYPE", "private")
    entity_mode = resolve_entity_mode(entity_type_raw)
    if args.resume_from_batch < 1:
        raise SystemExit("--resume-from-batch must be >= 1")

    run_started = datetime.now(timezone.utc)
    log_path = (
        logs_dir()
        / f"refresh_stale_entities_{entity_mode.name}_{run_started.strftime('%Y%m%d_%H%M%S')}.log"
    )
    logger = setup_logging(log_path)

    tenant_id = (args.tenant_id or "").strip() or None

    logger.info("Run started")
    logger.info("Entity type: %s (payload type=%s)", entity_mode.name, entity_mode.payload_type)
    logger.info("Log file: %s", log_path)
    logger.info("SQL query:\n%s", stale_entities_query(entity_mode, tenant_id=tenant_id, include_all=args.all_entities))

    missing = missing_postgres_env()
    if missing:
        logger.error("Missing Postgres settings in .env: %s", ", ".join(missing))
        return 1

    if args.date_filter:
        date_filter = datetime.strptime(args.date_filter, "%Y-%m-%d").date()
    else:
        date_filter = first_of_current_month()

    excluded = excluded_tenant_ids()
    base_url = tessera_base_url()
    batch_size = max(1, args.batch_size)
    workers = 1 if args.dry_run else max(1, args.workers)

    logger.info("Date filter (updated_date <): %s", date_filter.isoformat())
    if args.all_entities:
        logger.info("Including all entities (ignoring stale date filter)")
    if tenant_id:
        logger.info("Tenant filter: %s", tenant_id)
    else:
        logger.info("Excluded tenant_id values: %s", excluded)
    logger.info("Tessera base URL: %s", base_url)
    logger.info("Batch size: %s", batch_size)
    logger.info("Parallel workers: %s", workers)
    if args.dry_run:
        logger.info("Dry run enabled — no API submissions")

    try:
        total_found = asyncio.run(
            count_stale_external_ids(
                mode=entity_mode,
                date_filter=date_filter,
                excluded_tenants=excluded,
                tenant_id=tenant_id,
                include_all=args.all_entities,
            )
        )
    except Exception as exc:
        logger.exception("Database query failed: %s", exc)
        return 1

    entities_to_submit = submit_count(total_found, args.limit)
    total_batches = batch_count(entities_to_submit, batch_size)

    if total_found == 0:
        print(f"\nNo stale {entity_mode.name} entities found — nothing to submit for refresh.\n")
        logger.info("No stale entities found — nothing to submit for refresh.")
        return 0

    if args.resume_from_batch > total_batches:
        logger.error(
            "--resume-from-batch %s exceeds total batches %s",
            args.resume_from_batch,
            total_batches,
        )
        return 1

    print_submission_plan(
        entity_mode=entity_mode,
        total_found=total_found,
        submit_count=entities_to_submit,
        batch_count=total_batches,
        batch_size=batch_size,
        dry_run=args.dry_run,
        limit=args.limit,
        resume_from_batch=args.resume_from_batch,
        logger=logger,
    )
    logger.info(
        "Count query complete — %s stale entities, %s batches to process",
        f"{total_found:,}",
        f"{total_batches:,}",
    )

    manual_token = _env("STALE_REFRESH_MANUAL_TOKEN") or None
    token_manager = TokenManager(
        sso_url=_env("MOODYS_SSO_URL", DEFAULT_SSO_URL),
        username=_env("MOODYS_SSO_USERNAME"),
        password=_env("MOODYS_SSO_PASSWORD"),
        max_age_seconds=TOKEN_MAX_AGE_SECONDS,
        logger=logger,
        manual_token=manual_token,
    )

    if not args.dry_run:
        try:
            token_manager.get_token()
        except Exception as exc:
            logger.error("Authentication failed: %s", exc)
            return 1

    session = create_http_session(workers) if workers == 1 else None

    try:
        ok_count, fail_count, skipped_count, run_results = asyncio.run(
            process_batches(
                mode=entity_mode,
                date_filter=date_filter,
                excluded_tenants=excluded,
                tenant_id=tenant_id,
                include_all=args.all_entities,
                batch_size=batch_size,
                limit=args.limit,
                resume_from_batch=args.resume_from_batch,
                total_batches=total_batches,
                workers=workers,
                dry_run=args.dry_run,
                session=session,
                token_manager=token_manager,
                base_url=base_url,
                logger=logger,
            )
        )
    except Exception as exc:
        logger.exception("Batch processing failed: %s", exc)
        return 1

    elapsed = (datetime.now(timezone.utc) - run_started).total_seconds()
    summary = {
        "entity_type": entity_mode.name,
        "payload_type": entity_mode.payload_type,
        "tenant_id": tenant_id,
        "include_all_entities": args.all_entities,
        "date_filter": date_filter.isoformat(),
        "stale_entities_found": total_found,
        "entities_to_submit": entities_to_submit,
        "total_batches": total_batches,
        "workers": workers,
        "batches_skipped": skipped_count,
        "resume_from_batch": args.resume_from_batch,
        "batches_ok": ok_count,
        "batches_failed": fail_count,
        "failed_batches": run_results,
        "elapsed_seconds": round(elapsed, 2),
        "dry_run": args.dry_run,
    }
    logger.info("Run summary: %s", json.dumps(summary, indent=2))
    logger.info(
        "Completed in %.2fs — batches ok=%s failed=%s",
        elapsed,
        ok_count,
        fail_count,
    )

    summary_path = log_path.with_suffix(".summary.json")
    summary_path.write_text(
        json.dumps({"summary": summary}, indent=2),
        encoding="utf-8",
    )
    logger.info("Summary JSON: %s", summary_path)

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
