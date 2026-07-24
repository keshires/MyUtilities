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

Both queries exclude tenant ``0014000000NXtS8`` and compare a stale-date column
against the first of the current month (override the cutoff with ``--date-filter``).

The compared column is selectable with ``--stale-date-column`` (or the
``STALE_REFRESH_STALE_DATE_COLUMN`` env var): ``updated_date`` (default) or
``pd_last_known_date``. In both cases a NULL value counts as stale.

Entities whose latest ``financialStmtDate`` is older than
``--financial-max-age-years`` (default 3; env ``STALE_REFRESH_FINANCIAL_MAX_AGE_YEARS``)
are excluded — their PD cannot advance, so refreshing them is wasted work.
A missing/empty ``financialStmtDate`` is kept. Pass ``0`` to disable the filter.

Tenant scoping:
  ``--tenant-id X``  — refresh one tenant (the excluded list still applies).
  ``--per-tenant``   — iterate every tenant with stale entities (minus excluded),
                       processing each separately with its own plan and summary.
  Excluded tenants are never refreshed, even if named.

Submission size:
  ``--one-per-request`` — send exactly one external_id per refreshEntities call
  (batch size 1); slower but avoids large-payload failures.

Monthly run:
  python refresh_stale_non_public_entities.py --entity-type custom --dry-run
  python refresh_stale_non_public_entities.py --entity-type private --dry-run
  python refresh_stale_non_public_entities.py --entity-type custom
  python refresh_stale_non_public_entities.py --entity-type private --workers 3
  python refresh_stale_non_public_entities.py --entity-type private --resume-from-batch 44
  python refresh_stale_non_public_entities.py --entity-type custom --per-tenant
  python refresh_stale_non_public_entities.py --entity-type custom --one-per-request
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import random
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

DEFAULT_MAX_RETRIES = 4  # retry attempts after the first try, for 5xx/429/network errors
RETRY_BACKOFF_BASE_SECONDS = 2.0
RETRY_BACKOFF_MAX_SECONDS = 30.0
# Transient server / rate-limit statuses worth retrying with backoff.
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

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
  {financial_clause}
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
  {financial_clause}
  {date_clause}
"""

# Distinct tenants that have at least one matching stale entity (minus excluded).
TENANTS_QUERY_BASE = """
SELECT DISTINCT tenant_id
FROM public.entity
WHERE data_type = 'Private'
  AND {custom_id_clause}
  AND external_id IS NOT NULL
  AND {tenant_clause}
  {financial_clause}
  {date_clause}
ORDER BY tenant_id
"""

STALE_DATE_COLUMNS = ("updated_date", "pd_last_known_date")
DEFAULT_STALE_DATE_COLUMN = "updated_date"
DATE_CLAUSE_ALL = ""

# Business rule: an entity is not worth refreshing if its latest financial
# statement is older than this many years — its PD cannot advance regardless.
DEFAULT_FINANCIAL_STMT_MAX_AGE_YEARS = 3


def stale_date_clause(column: str, alias: str = "") -> str:
    """Build the stale-date WHERE clause for the chosen column.

    ``column`` must come from :data:`STALE_DATE_COLUMNS`; it is validated by
    :func:`resolve_stale_date_column` before it reaches here, so interpolating
    it into the SQL is safe. ``alias`` optionally qualifies the column (e.g.
    ``e``) for the joined customized query.
    """
    col = f"{alias}.{column}" if alias else column
    return (
        f"AND (\n"
        f"        {col} IS NULL\n"
        f"        OR {col} < $1::timestamp\n"
        f"      )"
    )


def financial_stmt_clause(max_age_years: int, alias: str = "") -> str:
    """Restrict to entities whose financialStmtDate is missing or within
    ``max_age_years`` of now. ``max_age_years <= 0`` disables the filter.

    ``max_age_years`` is an int (validated by argparse), so formatting it into
    the SQL interval literal is safe. ``alias`` optionally qualifies
    ``entity_data`` (e.g. ``e``) for the joined customized query.
    """
    if max_age_years <= 0:
        return ""
    col = f"{alias}.entity_data" if alias else "entity_data"
    return (
        "AND (\n"
        f"        NULLIF({col} ->> 'financialStmtDate', '') IS NULL\n"
        f"        OR NULLIF({col} ->> 'financialStmtDate', '')::timestamp"
        f" >= (NOW() - INTERVAL '{max_age_years} years')\n"
        "      )"
    )


def resolve_stale_date_column(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    if not key:
        return DEFAULT_STALE_DATE_COLUMN
    if key not in STALE_DATE_COLUMNS:
        valid = ", ".join(STALE_DATE_COLUMNS)
        raise SystemExit(
            f"Invalid --stale-date-column {raw!r}. Choose one of: {valid}"
        )
    return key

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
    data_type: str = "Private"
    # signal_mode controls the query shape:
    #   "none"    -> flat entity query, no customization signal (custom).
    #   "require" -> joined query, AND <signal>  (private-customized, public-customized).
    #   "exclude" -> joined query, AND NOT <signal>  (private, refined to drop customized).
    # "require"/"exclude" join entity_custom_data / entity_scorecard /
    # entity_parent_group_support and add is_cap_entity = false.
    signal_mode: str = "none"


ENTITY_MODES: dict[str, EntityRefreshMode] = {
    "custom": EntityRefreshMode(
        name="custom",
        payload_type="non-public-customized",
        custom_id_clause="custom_id IS NOT NULL",
        description="Custom entities (custom_id IS NOT NULL)",
        data_type="Private",
        signal_mode="none",
    ),
    "private": EntityRefreshMode(
        name="private",
        payload_type="non-public",
        custom_id_clause="custom_id IS NULL",
        description="Private entities (custom_id IS NULL, NOT customized — excludes the customization signal)",
        data_type="Private",
        signal_mode="exclude",
    ),
    "private-customized": EntityRefreshMode(
        name="private-customized",
        payload_type="non-public-customized",
        custom_id_clause="custom_id IS NULL",
        description="Private customized (data_type Private, custom_id IS NULL, customization signal)",
        data_type="Private",
        signal_mode="require",
    ),
    "public-customized": EntityRefreshMode(
        name="public-customized",
        payload_type="public-customized",
        custom_id_clause="custom_id IS NULL",
        description="Public customized (data_type Public, custom_id IS NULL, customization signal)",
        data_type="Public",
        signal_mode="require",
    ),
}


def resolve_entity_mode(raw: str) -> EntityRefreshMode:
    key = (raw or "").strip().lower()
    aliases = {
        "customized": "custom",
        "customised": "custom",
        "private_customized": "private-customized",
        "privatecustomized": "private-customized",
        "public_customized": "public-customized",
        "publiccustomized": "public-customized",
    }
    key = aliases.get(key, key)
    if key not in ENTITY_MODES:
        valid = ", ".join(sorted(ENTITY_MODES))
        raise SystemExit(f"Invalid --entity-type {raw!r}. Choose one of: {valid}")
    return ENTITY_MODES[key]


def tenant_clause(
    *, tenant_id: str | None, include_all: bool = False, alias: str = ""
) -> str:
    """Tenant WHERE fragment. Param position: ``$1`` when ``include_all`` (no
    date param), else ``$2``. ``alias`` optionally qualifies ``tenant_id``.

    With ``alias=''`` this reproduces the TENANT_CLAUSE_* constants exactly.
    """
    col = f"{alias}.tenant_id" if alias else "tenant_id"
    param = "$1" if include_all else "$2"
    if tenant_id:
        return f"{col} = {param}::text"
    return f"{col} <> ALL({param}::text[])"


# ---------------------------------------------------------------------------
# Customized modes (private-customized / public-customized)
#
# The backend (edfx-tessera-service EntityRefreshRepository.get_entities_
# w_customizations) classifies an entity as customized by signals in
# entity_custom_data / entity_scorecard / entity_parent_group_support — NOT by
# custom_id. We mirror that signal but keep custom_id IS NULL so these modes
# stay disjoint from the existing `custom` (custom_id IS NOT NULL) mode.
# ---------------------------------------------------------------------------
CUSTOMIZED_JOINS = (
    "FROM public.entity e\n"
    "LEFT JOIN public.entity_custom_data ecd ON ecd.entity_id = e.id\n"
    "LEFT JOIN public.entity_scorecard es ON es.entity_id = e.id\n"
    "LEFT JOIN public.entity_parent_group_support epgs ON epgs.entity_id = e.id"
)

CUSTOMIZED_SIGNAL_SQL = (
    "(\n"
    "        (es.entity_id IS NOT NULL AND es.apply_pd = true)\n"
    "     OR (COALESCE(ecd.financials_type, 'moodys') <> 'moodys')\n"
    "     OR (ecd.country IS NOT NULL OR ecd.state IS NOT NULL OR ecd.industry IS NOT NULL\n"
    "         OR ecd.peer_group_id IS NOT NULL OR ecd.target_cdt IS NOT NULL)\n"
    "     OR (epgs.entity_id IS NOT NULL AND epgs.apply_pd = true)\n"
    "      )"
)


def customized_entities_query(
    mode: EntityRefreshMode,
    *,
    select: str,
    order: str,
    tenant_id: str | None,
    include_all: bool,
    stale_date_column: str,
    financial_max_age_years: int,
) -> str:
    """Joined + signal-filtered query for customized modes. ``mode.data_type``
    ('Private'/'Public') comes from the validated ENTITY_MODES table, so
    interpolation is safe. Params: ``$1`` = stale cutoff, ``$2`` = tenant/excluded.
    """
    date_clause = (
        DATE_CLAUSE_ALL if include_all else stale_date_clause(stale_date_column, alias="e")
    )
    # require -> AND <signal> (customized modes; NULL/false excluded, i.e. only clearly customized).
    # exclude -> AND NOT COALESCE(<signal>, false) (refined private; NULL signal counts as
    #   not-customized so private is the exact complement of the customized modes — no gap).
    signal_clause = (
        f"NOT COALESCE({CUSTOMIZED_SIGNAL_SQL}, false)"
        if mode.signal_mode == "exclude"
        else CUSTOMIZED_SIGNAL_SQL
    )
    return (
        f"SELECT {select}\n"
        f"{CUSTOMIZED_JOINS}\n"
        f"WHERE e.data_type = '{mode.data_type}'\n"
        f"  AND e.custom_id IS NULL\n"
        f"  AND e.external_id IS NOT NULL\n"
        f"  AND e.is_cap_entity = false\n"
        f"  AND {signal_clause}\n"
        f"  AND {tenant_clause(tenant_id=tenant_id, include_all=include_all, alias='e')}\n"
        f"  {financial_stmt_clause(financial_max_age_years, alias='e')}\n"
        f"  {date_clause}\n"
        f"{order}"
    )


def stale_entities_query(
    mode: EntityRefreshMode,
    *,
    tenant_id: str | None = None,
    include_all: bool = False,
    stale_date_column: str = DEFAULT_STALE_DATE_COLUMN,
    financial_max_age_years: int = DEFAULT_FINANCIAL_STMT_MAX_AGE_YEARS,
) -> str:
    if mode.signal_mode != "none":
        return customized_entities_query(
            mode,
            select="DISTINCT e.external_id",
            order="ORDER BY e.external_id",
            tenant_id=tenant_id,
            include_all=include_all,
            stale_date_column=stale_date_column,
            financial_max_age_years=financial_max_age_years,
        )
    return STALE_ENTITIES_QUERY_BASE.format(
        custom_id_clause=mode.custom_id_clause,
        tenant_clause=tenant_clause(tenant_id=tenant_id, include_all=include_all),
        financial_clause=financial_stmt_clause(financial_max_age_years),
        date_clause=DATE_CLAUSE_ALL if include_all else stale_date_clause(stale_date_column),
    )


def stale_entities_count_query(
    mode: EntityRefreshMode,
    *,
    tenant_id: str | None = None,
    include_all: bool = False,
    stale_date_column: str = DEFAULT_STALE_DATE_COLUMN,
    financial_max_age_years: int = DEFAULT_FINANCIAL_STMT_MAX_AGE_YEARS,
) -> str:
    if mode.signal_mode != "none":
        return customized_entities_query(
            mode,
            select="COUNT(DISTINCT e.external_id)",
            order="",
            tenant_id=tenant_id,
            include_all=include_all,
            stale_date_column=stale_date_column,
            financial_max_age_years=financial_max_age_years,
        )
    return STALE_ENTITIES_COUNT_QUERY_BASE.format(
        custom_id_clause=mode.custom_id_clause,
        tenant_clause=tenant_clause(tenant_id=tenant_id, include_all=include_all),
        financial_clause=financial_stmt_clause(financial_max_age_years),
        date_clause=DATE_CLAUSE_ALL if include_all else stale_date_clause(stale_date_column),
    )


def tenants_query(
    mode: EntityRefreshMode,
    *,
    include_all: bool = False,
    stale_date_column: str = DEFAULT_STALE_DATE_COLUMN,
    financial_max_age_years: int = DEFAULT_FINANCIAL_STMT_MAX_AGE_YEARS,
) -> str:
    """Distinct non-excluded tenants with matching stale entities. Always uses
    the exclude form of the tenant clause (tenant_id param is the excluded list)."""
    if mode.signal_mode != "none":
        return customized_entities_query(
            mode,
            select="DISTINCT e.tenant_id",
            order="ORDER BY e.tenant_id",
            tenant_id=None,
            include_all=include_all,
            stale_date_column=stale_date_column,
            financial_max_age_years=financial_max_age_years,
        )
    return TENANTS_QUERY_BASE.format(
        custom_id_clause=mode.custom_id_clause,
        tenant_clause=tenant_clause(tenant_id=None, include_all=include_all),
        financial_clause=financial_stmt_clause(financial_max_age_years),
        date_clause=DATE_CLAUSE_ALL if include_all else stale_date_clause(stale_date_column),
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
    stale_date_column: str,
    financial_max_age_years: int,
) -> int:
    conn = await pg_connect()
    try:
        tenant_param = tenant_id if tenant_id else excluded_tenants
        query = stale_entities_count_query(
            mode,
            tenant_id=tenant_id,
            include_all=include_all,
            stale_date_column=stale_date_column,
            financial_max_age_years=financial_max_age_years,
        )
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


def read_completed_tenants(path: Path) -> set[str]:
    """Tenant ids already recorded as done in the checkpoint file (may not exist)."""
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def append_completed_tenant(path: Path, tenant_id: str) -> None:
    """Record a tenant as done so a resumed run skips it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"{tenant_id}\n")


async def discover_tenants(
    *,
    mode: EntityRefreshMode,
    date_filter: date,
    excluded_tenants: list[str],
    include_all: bool,
    stale_date_column: str,
    financial_max_age_years: int,
) -> list[str]:
    """Distinct tenant_ids (minus excluded) that have matching stale entities."""
    conn = await pg_connect()
    try:
        query = tenants_query(
            mode,
            include_all=include_all,
            stale_date_column=stale_date_column,
            financial_max_age_years=financial_max_age_years,
        )
        if include_all:
            rows = await conn.fetch(query, excluded_tenants)
        else:
            rows = await conn.fetch(
                query,
                datetime.combine(date_filter, datetime.min.time()),
                excluded_tenants,
            )
        return [str(r["tenant_id"]) for r in rows if r["tenant_id"] is not None]
    finally:
        await conn.close()


async def iter_stale_batches(
    *,
    mode: EntityRefreshMode,
    date_filter: date,
    excluded_tenants: list[str],
    tenant_id: str | None,
    include_all: bool,
    stale_date_column: str,
    financial_max_age_years: int,
    batch_size: int,
    limit: int | None,
    resume_from_batch: int,
    allowed_ids: set[str] | None = None,
) -> AsyncIterator[tuple[int, list[str], bool]]:
    """Stream entity ids from Postgres in submission-sized batches.

    ``allowed_ids`` (set by --pd-precheck) restricts the stream to those external_ids.
    """
    conn = await pg_connect()
    cutoff = datetime.combine(date_filter, datetime.min.time())
    tenant_param = tenant_id if tenant_id else excluded_tenants
    batch_num = 0
    current: list[str] = []
    seen = 0
    query = stale_entities_query(
        mode,
        tenant_id=tenant_id,
        include_all=include_all,
        stale_date_column=stale_date_column,
        financial_max_age_years=financial_max_age_years,
    )

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
                if allowed_ids is not None and str(external_id) not in allowed_ids:
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


def retry_backoff_seconds(retry_index: int) -> float:
    """Exponential backoff (base * 2^(n-1)), capped, with up to 25% jitter."""
    delay = RETRY_BACKOFF_BASE_SECONDS * (2 ** max(0, retry_index - 1))
    delay = min(delay, RETRY_BACKOFF_MAX_SECONDS)
    return delay + random.uniform(0, delay * 0.25)


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
    max_retries: int = DEFAULT_MAX_RETRIES,
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

    retries_used = 0  # backoff retries consumed (5xx / 429 / network)
    token_refresh_used = False  # 401 token refresh (one-shot, not a backoff retry)
    force_token_refresh = False
    attempt_no = 0

    while True:
        attempt_no += 1
        token = token_manager.get_token(force_refresh=force_token_refresh)
        force_token_refresh = False
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
                attempt_no,
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
            if retries_used < max_retries:
                retries_used += 1
                delay = retry_backoff_seconds(retries_used)
                logger.warning(
                    "Batch %s/%s request error (%s) — retry %s/%s in %.1fs",
                    batch_num,
                    total_batches,
                    exc,
                    retries_used,
                    max_retries,
                    delay,
                )
                time.sleep(delay)
                continue
            logger.error(
                "Batch %s/%s request failed after %s retries: %s",
                batch_num,
                total_batches,
                max_retries,
                exc,
            )
            return batch_num, False, 0, str(exc)

        body_preview = (response.text or "")[:1000]
        status = response.status_code

        # 401 → refresh token once and retry immediately (not a backoff retry).
        if status == 401 and not token_refresh_used:
            token_refresh_used = True
            force_token_refresh = True
            logger.warning(
                "Batch %s/%s HTTP 401 — refreshing token and retrying",
                batch_num,
                total_batches,
            )
            token_manager.invalidate()
            continue

        # Transient server / rate-limit errors → backoff retry while budget remains.
        if status in RETRYABLE_STATUS_CODES and retries_used < max_retries:
            retries_used += 1
            delay = retry_backoff_seconds(retries_used)
            logger.warning(
                "Batch %s/%s HTTP %s — retry %s/%s in %.1fs",
                batch_num,
                total_batches,
                status,
                retries_used,
                max_retries,
                delay,
            )
            time.sleep(delay)
            continue

        ok = response.ok
        if ok:
            if verbose:
                logger.info(
                    "Batch %s/%s succeeded: HTTP %s — %s",
                    batch_num,
                    total_batches,
                    status,
                    body_preview,
                )
        else:
            logger.error(
                "Batch %s/%s failed: HTTP %s (after %s retries) — %s",
                batch_num,
                total_batches,
                status,
                retries_used,
                body_preview,
            )
        return batch_num, ok, status, body_preview


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
    stale_date_column: str,
    financial_max_age_years: int,
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
    max_retries: int = DEFAULT_MAX_RETRIES,
    allowed_ids: set[str] | None = None,
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
            stale_date_column=stale_date_column,
            financial_max_age_years=financial_max_age_years,
            batch_size=batch_size,
            limit=limit,
            resume_from_batch=resume_from_batch,
            allowed_ids=allowed_ids,
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
                max_retries=max_retries,
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
            stale_date_column=stale_date_column,
            financial_max_age_years=financial_max_age_years,
            batch_size=batch_size,
            limit=limit,
            resume_from_batch=resume_from_batch,
            allowed_ids=allowed_ids,
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
                max_retries=max_retries,
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


def execute_refresh(
    *,
    scope_tenant_id: str | None,
    scope_index: int,
    scope_total: int,
    mode: EntityRefreshMode,
    date_filter: date,
    excluded: list[str],
    include_all: bool,
    stale_date_column: str,
    financial_max_age_years: int,
    batch_size: int,
    limit: int | None,
    resume_from_batch: int,
    workers: int,
    dry_run: bool,
    session: requests.Session | None,
    token_manager: TokenManager,
    base_url: str,
    max_retries: int,
    logger: logging.Logger,
    allowed_ids: set[str] | None = None,
) -> dict[str, object]:
    """Run the refresh for one scope — a single tenant, or all non-excluded
    tenants when ``scope_tenant_id`` is None. Returns a per-scope summary dict
    whose ``status`` is ``ok`` | ``empty`` | ``error``.

    ``allowed_ids`` (from --pd-precheck) restricts submissions to those external_ids."""
    scope_started = datetime.now(timezone.utc)
    label = scope_tenant_id or "<all non-excluded>"
    if scope_total > 1:
        logger.info("=== Tenant %s/%s: %s ===", scope_index, scope_total, label)

    summary: dict[str, object] = {
        "tenant_id": scope_tenant_id,
        "stale_entities_found": 0,
        "entities_to_submit": 0,
        "total_batches": 0,
        "batches_skipped": 0,
        "batches_ok": 0,
        "batches_failed": 0,
        "failed_batches": [],
        "elapsed_seconds": 0.0,
        "status": "empty",
    }

    try:
        total_found = asyncio.run(
            count_stale_external_ids(
                mode=mode,
                date_filter=date_filter,
                excluded_tenants=excluded,
                tenant_id=scope_tenant_id,
                include_all=include_all,
                stale_date_column=stale_date_column,
                financial_max_age_years=financial_max_age_years,
            )
        )
    except Exception as exc:
        logger.exception("Scope %s: count query failed: %s", label, exc)
        summary["status"] = "error"
        summary["note"] = f"count failed: {exc}"
        return summary

    entities_to_submit = submit_count(total_found, limit)
    total_batches = batch_count(entities_to_submit, batch_size)
    summary["stale_entities_found"] = total_found
    summary["entities_to_submit"] = entities_to_submit
    summary["total_batches"] = total_batches

    if total_found == 0:
        logger.info("Scope %s: no stale entities — skipping.", label)
        summary["elapsed_seconds"] = round(
            (datetime.now(timezone.utc) - scope_started).total_seconds(), 2
        )
        return summary

    if resume_from_batch > total_batches:
        logger.error(
            "Scope %s: --resume-from-batch %s exceeds total batches %s",
            label,
            resume_from_batch,
            total_batches,
        )
        summary["status"] = "error"
        summary["note"] = "resume-from-batch exceeds total batches"
        return summary

    print_submission_plan(
        entity_mode=mode,
        total_found=total_found,
        submit_count=entities_to_submit,
        batch_count=total_batches,
        batch_size=batch_size,
        dry_run=dry_run,
        limit=limit,
        resume_from_batch=resume_from_batch,
        logger=logger,
    )

    try:
        ok_count, fail_count, skipped_count, run_results = asyncio.run(
            process_batches(
                mode=mode,
                date_filter=date_filter,
                excluded_tenants=excluded,
                tenant_id=scope_tenant_id,
                include_all=include_all,
                stale_date_column=stale_date_column,
                financial_max_age_years=financial_max_age_years,
                batch_size=batch_size,
                limit=limit,
                resume_from_batch=resume_from_batch,
                total_batches=total_batches,
                workers=workers,
                dry_run=dry_run,
                session=session,
                token_manager=token_manager,
                base_url=base_url,
                logger=logger,
                max_retries=max_retries,
                allowed_ids=allowed_ids,
            )
        )
    except Exception as exc:
        logger.exception("Scope %s: batch processing failed: %s", label, exc)
        summary["status"] = "error"
        summary["note"] = f"processing failed: {exc}"
        return summary

    elapsed = (datetime.now(timezone.utc) - scope_started).total_seconds()
    summary.update(
        {
            "batches_skipped": skipped_count,
            "batches_ok": ok_count,
            "batches_failed": fail_count,
            "failed_batches": run_results,
            "elapsed_seconds": round(elapsed, 2),
            "status": "ok",
        }
    )
    logger.info(
        "Scope %s complete in %.2fs — batches ok=%s failed=%s",
        label,
        elapsed,
        ok_count,
        fail_count,
    )
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--entity-type",
        default=None,
        help=(
            "Entity mode: 'custom' (custom_id NOT NULL -> non-public-customized), "
            "'private' (custom_id NULL -> non-public), "
            "'private-customized' (custom_id NULL + customization signal -> non-public-customized), "
            "'public-customized' (Public + custom_id NULL + signal -> public-customized). "
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
        "--stale-date-column",
        type=str,
        default=None,
        choices=STALE_DATE_COLUMNS,
        help=(
            "Column compared against the stale cutoff. "
            f"Choices: {', '.join(STALE_DATE_COLUMNS)}. "
            "Default: STALE_REFRESH_STALE_DATE_COLUMN or "
            f"'{DEFAULT_STALE_DATE_COLUMN}'."
        ),
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
        "--financial-max-age-years",
        type=int,
        default=int(
            os.getenv(
                "STALE_REFRESH_FINANCIAL_MAX_AGE_YEARS",
                str(DEFAULT_FINANCIAL_STMT_MAX_AGE_YEARS),
            )
        ),
        help=(
            "Only refresh entities whose financialStmtDate is missing or within "
            f"this many years of now (default: {DEFAULT_FINANCIAL_STMT_MAX_AGE_YEARS}). "
            "Use 0 to disable this filter."
        ),
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=int(os.getenv("STALE_REFRESH_MAX_RETRIES", str(DEFAULT_MAX_RETRIES))),
        help=(
            "Retry attempts (with exponential backoff) per batch on HTTP "
            f"{sorted(RETRYABLE_STATUS_CODES)} or network errors "
            f"(default: {DEFAULT_MAX_RETRIES}). Use 0 to disable retries."
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
        help=(
            "Restrict refresh to a single tenant_id. The excluded-tenant list "
            "still applies (an excluded tenant is refused)."
        ),
    )
    parser.add_argument(
        "--per-tenant",
        action="store_true",
        help=(
            "Refresh tenant-by-tenant: discover every tenant with stale entities "
            "(minus excluded) and process each separately. Mutually exclusive with "
            "--tenant-id; incompatible with --resume-from-batch."
        ),
    )
    parser.add_argument(
        "--one-per-request",
        action="store_true",
        help=(
            "Submit exactly one external_id per refreshEntities call (batch size 1). "
            "Slower, but avoids large-payload failures."
        ),
    )
    parser.add_argument(
        "--pd-precheck",
        action="store_true",
        help=(
            "Before posting, classify each stale entity (entity PD + peer-group PD) and "
            "submit only genuine candidates — skip already-fresh and peer-group-matched. "
            "Requires --stale-date-column pd_last_known_date."
        ),
    )
    parser.add_argument(
        "--allow-ids-file",
        type=str,
        default=None,
        help=(
            "Restrict posting to the external_ids listed in this file (one per line) — "
            "e.g. the POST-category ids from a validate_pd_precheck report. Only entities "
            "in both the stale set and this file are submitted."
        ),
    )
    parser.add_argument(
        "--tenant-checkpoint",
        type=str,
        default=None,
        help=(
            "Per-tenant checkpoint file (use with --per-tenant). Tenants already "
            "listed are skipped; each tenant is appended as it completes, so "
            "re-running with the same file resumes without re-processing tenants."
        ),
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
    stale_date_column = resolve_stale_date_column(
        args.stale_date_column or _env("STALE_REFRESH_STALE_DATE_COLUMN")
    )
    if args.resume_from_batch < 1:
        raise SystemExit("--resume-from-batch must be >= 1")
    if args.per_tenant and args.tenant_id:
        raise SystemExit("--per-tenant and --tenant-id are mutually exclusive.")
    if args.per_tenant and args.resume_from_batch > 1:
        raise SystemExit("--resume-from-batch is not supported with --per-tenant.")

    run_started = datetime.now(timezone.utc)
    log_path = (
        logs_dir("refresh_stale_entities")
        / f"refresh_stale_entities_{entity_mode.name}_{run_started.strftime('%Y%m%d_%H%M%S')}.log"
    )
    logger = setup_logging(log_path)

    tenant_id = (args.tenant_id or "").strip() or None

    logger.info("Run started")
    logger.info("Entity type: %s (payload type=%s)", entity_mode.name, entity_mode.payload_type)
    logger.info("Log file: %s", log_path)
    financial_max_age_years = max(0, args.financial_max_age_years)
    logger.info("Stale date column: %s", stale_date_column)
    logger.info(
        "Financial statement max age: %s",
        f"{financial_max_age_years} years" if financial_max_age_years > 0 else "disabled",
    )
    logger.info(
        "SQL query:\n%s",
        stale_entities_query(
            entity_mode,
            tenant_id=tenant_id,
            include_all=args.all_entities,
            stale_date_column=stale_date_column,
            financial_max_age_years=financial_max_age_years,
        ),
    )

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
    batch_size = 1 if args.one_per_request else max(1, args.batch_size)
    workers = 1 if args.dry_run else max(1, args.workers)
    max_retries = max(0, args.max_retries)

    # Exclusion always wins: a named excluded tenant is refused.
    if tenant_id and tenant_id in excluded:
        logger.warning(
            "Tenant %s is in the excluded list — nothing to refresh (exclusion always wins).",
            tenant_id,
        )
        print(f"\nTenant {tenant_id} is excluded — nothing to do.\n")
        return 0

    logger.info("Stale cutoff (%s <): %s", stale_date_column, date_filter.isoformat())
    if args.one_per_request:
        logger.info("One-per-request mode: batch size forced to 1")
    if args.all_entities:
        logger.info("Including all entities (ignoring stale date filter)")
    if tenant_id:
        logger.info("Tenant filter: %s (exclusion still applies)", tenant_id)
    elif args.per_tenant:
        logger.info("Per-tenant mode; excluded tenant_id values: %s", excluded)
    else:
        logger.info("Excluded tenant_id values: %s", excluded)
    logger.info("Tessera base URL: %s", base_url)
    logger.info("Batch size: %s", batch_size)
    logger.info("Parallel workers: %s", workers)
    logger.info(
        "Max retries per batch: %s (statuses %s + network errors)",
        max_retries,
        sorted(RETRYABLE_STATUS_CODES),
    )
    if args.dry_run:
        logger.info("Dry run enabled — no API submissions")

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

    checkpoint_path = Path(args.tenant_checkpoint) if args.tenant_checkpoint else None
    tenants_skipped_by_checkpoint = 0

    # PD pre-check: classify the stale set and keep only genuine POST candidates.
    precheck_ids: set[str] | None = None
    if args.allow_ids_file:
        import pd_precheck as pc

        precheck_ids = pc.load_ids_file(args.allow_ids_file)
        logger.info(
            "Allow-ids file %s: restricting posts to %s external_ids",
            args.allow_ids_file, len(precheck_ids),
        )
        if not precheck_ids:
            print("\nAllow-ids file is empty — nothing to post.\n")
            return 0
    elif args.pd_precheck:
        if stale_date_column != "pd_last_known_date":
            raise SystemExit("--pd-precheck requires --stale-date-column pd_last_known_date")
        import pd_precheck as pc

        async def _fetch_precheck_rows() -> list["pc.StaleRow"]:
            conn = await pg_connect()
            try:
                q = f"""SELECT DISTINCT ON (e.external_id)
                               e.external_id, e.tenant_id, e.pd_last_known_date,
                               e.entity_data->>'peerId' AS peer_id,
                               COALESCE(e.entity_data->>'isPeerDriven','') AS ipd
                        FROM public.entity e
                        WHERE e.data_type='Private' AND {entity_mode.custom_id_clause}
                          AND e.external_id IS NOT NULL AND {tenant_clause(tenant_id=tenant_id)}
                          {financial_stmt_clause(financial_max_age_years)}
                          {stale_date_clause(stale_date_column)}
                        ORDER BY e.external_id, e.pd_last_known_date DESC NULLS LAST"""
                params = [
                    datetime.combine(date_filter, datetime.min.time()),
                    tenant_id if tenant_id else excluded,
                ]
                rows = await conn.fetch(q, *params)
            finally:
                await conn.close()
            return [
                pc.StaleRow(str(r["external_id"]), str(r["tenant_id"]),
                            r["pd_last_known_date"], r["peer_id"], r["ipd"] == "true")
                for r in rows
            ]

        def _fetch_group(ids: list[str]) -> list[tuple[str, "date | None"]]:
            async def run():
                conn = await pg_connect()
                try:
                    return await conn.fetch(
                        "SELECT entity_data->>'peerId' pid, MAX(pd_last_known_date) mx "
                        "FROM public.entity WHERE entity_data->>'peerId' = ANY($1::text[]) GROUP BY 1",
                        ids,
                    )
                finally:
                    await conn.close()

            return [(str(r["pid"]), r["mx"]) for r in asyncio.run(run())]

        _precheck_rows = asyncio.run(_fetch_precheck_rows())
        precheck_ids = pc.post_ids(
            _precheck_rows, pc.DbMaxPeerGroupPdResolver(_fetch_group),
            entity_mode.name, pc.month_start(date.today()),
        )
        logger.info(
            "PD pre-check: %s of %s stale entities will be posted (%s skipped)",
            len(precheck_ids), len(_precheck_rows), len(_precheck_rows) - len(precheck_ids),
        )
        if not precheck_ids:
            print("\nPD pre-check: nothing to post after filtering.\n")
            return 0

    # Decide the scopes to process.
    if args.per_tenant:
        try:
            tenants = asyncio.run(
                discover_tenants(
                    mode=entity_mode,
                    date_filter=date_filter,
                    excluded_tenants=excluded,
                    include_all=args.all_entities,
                    stale_date_column=stale_date_column,
                    financial_max_age_years=financial_max_age_years,
                )
            )
        except Exception as exc:
            logger.exception("Tenant discovery failed: %s", exc)
            return 1
        if not tenants:
            print(f"\nNo stale {entity_mode.name} entities in any tenant — nothing to refresh.\n")
            logger.info("No tenants with stale entities.")
            return 0
        discovered = len(tenants)
        if checkpoint_path:
            done = read_completed_tenants(checkpoint_path)
            tenants = [t for t in tenants if t not in done]
            tenants_skipped_by_checkpoint = discovered - len(tenants)
            logger.info(
                "Checkpoint %s: %s tenant(s) already done, %s remaining (of %s discovered)",
                checkpoint_path,
                tenants_skipped_by_checkpoint,
                len(tenants),
                discovered,
            )
            if not tenants:
                print("\nAll discovered tenants already completed per checkpoint — nothing to do.\n")
                logger.info("All tenants already completed per checkpoint.")
                return 0
        logger.info("Per-tenant mode: %s tenant(s) to process this run", len(tenants))
        scopes: list[str | None] = list(tenants)
        mode_label = "per-tenant"
    elif tenant_id:
        scopes = [tenant_id]
        mode_label = "single"
    else:
        scopes = [None]
        mode_label = "all"

    scope_summaries: list[dict[str, object]] = []
    for i, scope in enumerate(scopes, start=1):
        scope_summary = execute_refresh(
            scope_tenant_id=scope,
            scope_index=i,
            scope_total=len(scopes),
            mode=entity_mode,
            date_filter=date_filter,
            excluded=excluded,
            include_all=args.all_entities,
            stale_date_column=stale_date_column,
            financial_max_age_years=financial_max_age_years,
            batch_size=batch_size,
            limit=args.limit,
            resume_from_batch=args.resume_from_batch,
            workers=workers,
            dry_run=args.dry_run,
            session=session,
            token_manager=token_manager,
            base_url=base_url,
            max_retries=max_retries,
            logger=logger,
            allowed_ids=precheck_ids,
        )
        scope_summaries.append(scope_summary)
        # Record a completed tenant so a resumed run skips it. Only when it fully
        # succeeded (no failed batches) and not in a dry run.
        if (
            checkpoint_path
            and scope is not None
            and not args.dry_run
            and scope_summary["status"] in ("ok", "empty")
            and int(scope_summary["batches_failed"]) == 0
        ):
            append_completed_tenant(checkpoint_path, scope)

    elapsed = (datetime.now(timezone.utc) - run_started).total_seconds()
    totals = {
        "stale_entities_found": sum(int(s["stale_entities_found"]) for s in scope_summaries),
        "entities_to_submit": sum(int(s["entities_to_submit"]) for s in scope_summaries),
        "total_batches": sum(int(s["total_batches"]) for s in scope_summaries),
        "batches_ok": sum(int(s["batches_ok"]) for s in scope_summaries),
        "batches_failed": sum(int(s["batches_failed"]) for s in scope_summaries),
        "tenants_processed": sum(1 for s in scope_summaries if s["status"] == "ok"),
        "tenants_empty": sum(1 for s in scope_summaries if s["status"] == "empty"),
        "tenants_error": sum(1 for s in scope_summaries if s["status"] == "error"),
    }
    summary = {
        "entity_type": entity_mode.name,
        "payload_type": entity_mode.payload_type,
        "mode": mode_label,
        "include_all_entities": args.all_entities,
        "stale_date_column": stale_date_column,
        "financial_max_age_years": financial_max_age_years,
        "date_filter": date_filter.isoformat(),
        "batch_size": batch_size,
        "one_per_request": args.one_per_request,
        "pd_precheck": args.pd_precheck,
        "allow_ids_file": args.allow_ids_file,
        "pd_precheck_posted": len(precheck_ids) if precheck_ids is not None else None,
        "workers": workers,
        "max_retries": max_retries,
        "resume_from_batch": args.resume_from_batch,
        "dry_run": args.dry_run,
        "tenant_checkpoint": str(checkpoint_path) if checkpoint_path else None,
        "tenants_skipped_by_checkpoint": tenants_skipped_by_checkpoint,
        "elapsed_seconds": round(elapsed, 2),
        "totals": totals,
        "tenants": scope_summaries,
    }
    logger.info("Run summary: %s", json.dumps(summary, indent=2))
    logger.info(
        "Completed in %.2fs — tenants ok=%s empty=%s error=%s; batches ok=%s failed=%s",
        elapsed,
        totals["tenants_processed"],
        totals["tenants_empty"],
        totals["tenants_error"],
        totals["batches_ok"],
        totals["batches_failed"],
    )
    if totals["stale_entities_found"] == 0:
        print(f"\nNo stale {entity_mode.name} entities found — nothing to submit for refresh.\n")

    summary_path = log_path.with_suffix(".summary.json")
    summary_path.write_text(
        json.dumps({"summary": summary}, indent=2),
        encoding="utf-8",
    )
    logger.info("Summary JSON: %s", summary_path)

    had_error = totals["tenants_error"] > 0 or totals["batches_failed"] > 0
    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
