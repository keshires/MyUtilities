"""
Delete a custom entity via the EDFX Financials API (DELETE).

Example (one or many ids — comma-separated):
  python financials_delete_custom_entity.py ^
    --entity-id ff078c4644fe48cb8c8f4cfd1345648f,another-id ^
    --token YOUR_BEARER_TOKEN

Token: ``--token``, or environment variable ``EDFX_TOKEN`` (recommended for VS Code — see ``.vscode/launch.json`` + ``envFile``).

Entity ids: pass ``--entity-id`` (comma-separated), or set ``EDFX_DELETE_ENTITY_IDS`` in ``.env`` with the same comma-separated list.

Optional cookie: ``--cookie`` or ``EDFX_COOKIE`` in ``.env`` (e.g. Cloudflare ``__cf_bm``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)


def get_edfx_token() -> str:
    """Fetch a bearer token from Moody's SSO using env credentials."""
    sso_url = (os.environ.get("MOODYS_SSO_URL") or "https://sso.moodysanalytics.com/sso-api/v1/token").strip()
    username = (os.environ.get("MOODYS_SSO_USERNAME") or "").strip()
    password = (os.environ.get("MOODYS_SSO_PASSWORD") or "").strip()
    if not username or not password:
        raise SystemExit(
            "Auto-token requires MOODYS_SSO_USERNAME and MOODYS_SSO_PASSWORD in .env "
            "(or provide --token / EDFX_TOKEN directly)."
        )
    print(f"Fetching SSO token for {username} ...")
    resp = requests.post(
        sso_url,
        data={"username": username, "password": password, "grant_type": "password", "scope": "openid"},
        headers={"Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("id_token") or data.get("access_token")
    if not token:
        raise SystemExit(f"SSO response did not contain a token. Response keys: {list(data.keys())}")
    print("  SSO token obtained.")
    return token


def parse_entity_ids(raw: str) -> list[str]:
    """Split comma-separated entity ids; strip whitespace; drop empties."""
    return [part.strip() for part in raw.split(",") if part.strip()]


def fetch_entity_ids_from_tessera(tenant_id: str, limit: int | None = None) -> list[str]:
    """Query Tessera Postgres for duplicate custom entity external_ids to delete.

    Returns all newer duplicates per (custom_id, tenant_id) group — rank > 1 by created_date ASC.
    The oldest copy (rank=1) is kept. These external_id values map directly to the EDFX delete API entity id parameter.
    """
    try:
        import psycopg2
    except ImportError:
        raise SystemExit("psycopg2-binary is required for --from-db. Install: pip install psycopg2-binary")

    host = (os.environ.get("TESSERA_POSTGRES_HOST") or "").strip()
    port = int(os.environ.get("TESSERA_POSTGRES_PORT") or "5432")
    dbname = (os.environ.get("TESSERA_POSTGRES_DB") or "").strip()
    user = (os.environ.get("TESSERA_POSTGRES_USER") or "").strip()
    password = (os.environ.get("TESSERA_POSTGRES_PASSWORD") or "").strip()

    if not host or not dbname or not user:
        raise SystemExit(
            "Missing Tessera connection vars. Set TESSERA_POSTGRES_HOST, "
            "TESSERA_POSTGRES_DB, TESSERA_POSTGRES_USER, TESSERA_POSTGRES_PASSWORD in .env."
        )

    # sql = """
    #     WITH dup_keys AS (
    #         SELECT ed.custom_id, ed.tenant_id
    #         FROM entity ed
    #         WHERE ed.custom_id IS NOT NULL
    #           AND ed.tenant_id = %(tenant_id)s
    #         GROUP BY ed.custom_id, ed.tenant_id
    #         HAVING COUNT(*) > 1
    #     ),
    #     Ranked AS (
    #         SELECT
    #             e.id                                 AS entity_id,
    #             e.tenant_id || '#' || e.external_id  AS tenant_external_key,
    #             e.name                               AS entity_name,
    #             e.custom_id,
    #             e.tenant_id,
    #             e.external_id,
    #             ecd.created_date,
    #             RANK() OVER (
    #                 PARTITION BY e.custom_id, e.tenant_id
    #                 ORDER BY ecd.created_date ASC NULLS LAST, e.external_id ASC
    #             ) AS creation_rank
    #         FROM entity e
    #         INNER JOIN dup_keys dk
    #             ON dk.tenant_id = e.tenant_id
    #            AND dk.custom_id = e.custom_id
    #         INNER JOIN entity_custom_data ecd
    #             ON ecd.tenant_id = e.tenant_id
    #            AND e.external_id = ecd.external_id
    #     )
    #     SELECT r.external_id
    #     FROM Ranked r
    #     WHERE creation_rank > 1
    #     ORDER BY r.custom_id
    # """

    sql = """
        SELECT e.external_id
        FROM portfolio_entity_link p
        JOIN entity e
            ON e.id = p.entity_id
           AND e.tenant_id = p.tenant_id
           AND e.custom_id IS NOT NULL
           AND e.tenant_id = %(tenant_id)s
        JOIN entity_custom_data eca
            ON e.id = eca.entity_id
           AND e.tenant_id = eca.tenant_id
        WHERE p.portfolio_id = 22666
          AND eca.created_date < '2026-07-25'
          AND eca.created_by = 'karthi.venkatraman@moodys.com'          
    """
    if limit:
        sql += f" LIMIT {limit}"

    print(f"Connecting to Tessera ({host}:{port}/{dbname}) for tenant {tenant_id!r} ...")
    try:
        conn = psycopg2.connect(
            host=host, port=port, dbname=dbname,
            user=user, password=password, connect_timeout=15,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(sql, {"tenant_id": tenant_id})
                rows = cur.fetchall()
        finally:
            conn.close()
    except psycopg2.Error as exc:
        raise SystemExit(f"Tessera query failed: {exc}") from exc

    ids = [str(row[0]).strip() for row in rows if row[0]]
    print(f"  Fetched {len(ids)} duplicate entity id(s) to delete from Tessera.")
    return ids


DEFAULT_BASE_URL = "https://api.edfx.moodysanalytics.com"


def delete_custom_entity(
    entity_id: str,
    token: str,
    base_url: str = DEFAULT_BASE_URL,
    cookie: str | None = None,
    tenant_id: str | None = None,
    timeout: float = 60.0,
) -> requests.Response:
    """Send DELETE .../financials/client/v1/customEntity/{entity_id}."""
    base = base_url.rstrip("/")
    url = f"{base}/financials/client/v1/customEntity/{entity_id}"

    headers: dict[str, str] = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if tenant_id:
        headers["x-tenant-id"] = tenant_id
    if cookie:
        headers["Cookie"] = cookie

    adapter = requests.adapters.HTTPAdapter(max_retries=0, pool_connections=1, pool_maxsize=1)
    with requests.Session() as session:
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session.delete(url, headers=headers, timeout=timeout)


def _response_message(resp: requests.Response) -> str:
    """Extract a single-line summary message from the response body."""
    ct = (resp.headers.get("Content-Type") or "").lower()
    text = resp.text.strip()
    if not text:
        return ""
    if "application/json" in ct:
        try:
            data: Any = resp.json()
            if isinstance(data, dict):
                return str(data.get("message") or data.get("status") or text[:200])
        except json.JSONDecodeError:
            pass
    return text[:200]


def _print_response(resp: requests.Response) -> None:
    print(f"HTTP {resp.status_code}")
    ct = (resp.headers.get("Content-Type") or "").lower()
    text = resp.text
    if not text:
        return
    if "application/json" in ct:
        try:
            data: Any = resp.json()
            print(json.dumps(data, indent=2))
        except json.JSONDecodeError:
            print(text)
    else:
        print(text)


class _TokenStore:
    """Shared token across workers; refreshes once on 401, other workers wait and reuse."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._lock = threading.Lock()

    def get(self) -> str:
        return self._token

    def refresh(self) -> tuple[str, str | None]:
        """Refresh token under lock; returns (new_token, error_msg)."""
        with self._lock:
            try:
                self._token = get_edfx_token()
                return self._token, None
            except (requests.RequestException, SystemExit) as exc:
                return "", f"SSO token refresh failed mid-run: {exc}"


def _delete_one(
    eid: str,
    idx: int,
    total: int,
    token_store: _TokenStore,
    base_url: str,
    cookie: str | None,
    tenant_id: str | None,
    timeout: float,
    print_lock: threading.Lock,
) -> tuple[int, str, "requests.Response | None", "str | None"]:
    """Delete one entity; retry once on 401. Connection errors returned immediately."""
    try:
        resp = delete_custom_entity(
            entity_id=eid,
            token=token_store.get(),
            base_url=base_url,
            cookie=cookie,
            tenant_id=tenant_id,
            timeout=timeout,
        )
    except requests.RequestException as ex:
        return idx, eid, None, str(ex)

    if resp.status_code == 401:
        new_token, err = token_store.refresh()
        if err:
            return idx, eid, None, err
        try:
            resp = delete_custom_entity(
                entity_id=eid,
                token=new_token,
                base_url=base_url,
                cookie=cookie,
                tenant_id=tenant_id,
                timeout=timeout,
            )
        except requests.RequestException as ex:
            return idx, eid, None, str(ex)

    return idx, eid, resp, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DELETE custom entity(s) (Bearer token + one or more entity ids)."
    )
    parser.add_argument(
        "--entity-id",
        default=None,
        help=(
            "Custom entity id(s): one UUID, or comma-separated list. "
            "If omitted, EDFX_DELETE_ENTITY_IDS from the environment / .env is used."
        ),
    )
    parser.add_argument(
        "--token",
        default=None,
        help="OAuth bearer token (no 'Bearer ' prefix). If omitted, EDFX_TOKEN env is used.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API host base URL (default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument(
        "--tenant-id",
        default="0014000000NXtS8",
        help="Tenant id sent as x-tenant-id header (default: 0014000000NXtS8). Overridden by EDFX_TENANT_ID env.",
    )
    parser.add_argument(
        "--cookie",
        default=None,
        help="Optional Cookie header value (e.g. Cloudflare __cf_bm if required).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Request timeout in seconds (default: 60).",
    )
    parser.add_argument(
        "--append-log",
        default=None,
        help="Path to an existing log file to append results to instead of creating a new one.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Number of parallel DELETE threads (default: 5). Set to 1 for sequential mode.",
    )
    parser.add_argument(
        "--from-db",
        action="store_true",
        default=False,
        help=(
            "Load entity ids from Tessera Postgres (duplicate custom entity query) "
            "instead of --entity-id / EDFX_DELETE_ENTITY_IDS. "
            "Uses TESSERA_POSTGRES_* and EDFX_TENANT_ID from .env."
        ),
    )
    parser.add_argument(
        "--db-limit",
        type=int,
        default=None,
        help="Max number of entity ids to fetch from Tessera (default: no limit).",
    )
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be at least 1.")

    token = (args.token or "").strip() or (os.environ.get("EDFX_TOKEN") or "").strip()
    if not token:
        try:
            token = get_edfx_token()
        except requests.RequestException as exc:
            raise SystemExit(f"SSO token fetch failed: {exc}") from exc

    tenant_id_val = (os.environ.get("EDFX_TENANT_ID") or "").strip() or (
        args.tenant_id or ""
    ).strip()

    if args.from_db:
        if not tenant_id_val:
            parser.error("--from-db requires EDFX_TENANT_ID in .env (or --tenant-id).")
        entity_ids = fetch_entity_ids_from_tessera(tenant_id=tenant_id_val, limit=args.db_limit)
        if not entity_ids:
            print("No duplicate entity ids found in Tessera for this tenant. Nothing to delete.")
            return 0
    else:
        raw_entity = (args.entity_id or "").strip() or (
            os.environ.get("EDFX_DELETE_ENTITY_IDS") or ""
        ).strip()
        entity_ids = parse_entity_ids(raw_entity)
        if not entity_ids:
            parser.error(
                "Provide entity ids via --entity-id / EDFX_DELETE_ENTITY_IDS, or use --from-db."
            )

    cookie_val = (args.cookie or "").strip() or (
        os.environ.get("EDFX_COOKIE") or ""
    ).strip()

    script_dir = Path(__file__).resolve().parent
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.append_log:
        log_path = Path(args.append_log)
        log_mode = "a"
    else:
        log_path = script_dir / f"delete_log_{ts}.log"
        log_mode = "w"
    failures_path = script_dir / f"delete_failures_{ts}.txt"

    failed = 0
    failed_ids: list[str] = []
    completed = 0
    conn_errors = 0
    run_start = datetime.now()
    batch_start = datetime.now()

    print_lock = threading.Lock()
    token_store = _TokenStore(token)
    total = len(entity_ids)
    print(f"Starting deletion of {total} entities with {args.workers} workers ... [{run_start.strftime('%Y-%m-%d %H:%M:%S')}]")

    with log_path.open(log_mode, encoding="utf-8") as log_f:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    _delete_one,
                    eid, i, total, token_store,
                    args.base_url, cookie_val or None, tenant_id_val or None,
                    args.timeout, print_lock,
                ): eid
                for i, eid in enumerate(entity_ids, start=1)
            }
            for future in as_completed(futures):
                try:
                    idx, eid, resp, err = future.result()
                except Exception as exc:
                    eid = futures[future]
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    reason = f"UNEXPECTED ERROR: {exc}"
                    log_f.write(f"{now} | entity_id={eid} | {reason}\n")
                    failed += 1
                    failed_ids.append((eid, reason))
                    continue
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if err:
                    if "SSO token refresh failed mid-run" in err:
                        log_f.write(f"{now} | [{idx}/{total}] | entity_id={eid} | FATAL | {err}\n")
                        ok_count = completed - failed
                        summary = f"Aborted. {ok_count} ok, {failed} failed (of {completed} processed / {total} total). Log: {log_path.name}"
                        print(f"\n{summary}", file=sys.stderr)
                        log_f.write(f"\n{summary}\n")
                        sys.exit(1)
                    log_f.write(f"{now} | [{idx}/{total}] | entity_id={eid} | ERROR | {err}\n")
                    failed += 1
                    failed_ids.append((eid, f"ERROR: {err}"))
                    if "Bad file descriptor" in err or "NewConnectionError" in err:
                        conn_errors += 1
                        if conn_errors >= args.workers:
                            ok_count = completed - failed
                            summary = f"Aborted — all workers hit connection errors. {ok_count} ok, {failed} failed (of {completed} processed / {total} total). Log: {log_path.name}"
                            print(f"\n{summary}", file=sys.stderr)
                            log_f.write(f"\n{summary}\n")
                            sys.exit(1)
                else:
                    msg = _response_message(resp)
                    log_f.write(f"{now} | [{idx}/{total}] | entity_id={eid} | HTTP {resp.status_code} | {msg}\n")
                    if not resp.ok:
                        failed += 1
                        failed_ids.append((eid, f"HTTP {resp.status_code}: {msg}"))

                completed += 1
                if completed % 500 == 0:
                    now_dt = datetime.now()
                    batch_secs = (now_dt - batch_start).total_seconds()
                    batch_dur = f"{batch_secs / 60:.1f}m" if batch_secs >= 60 else f"{batch_secs:.1f}s"
                    total_secs = (now_dt - run_start).total_seconds()
                    total_dur = f"{total_secs / 3600:.2f}h" if total_secs >= 3600 else f"{total_secs / 60:.1f}m" if total_secs >= 60 else f"{total_secs:.1f}s"
                    print(f"  Progress: {completed}/{total} | {failed} failed | batch: {batch_dur} | elapsed: {total_dur} | [{now_dt.strftime('%H:%M:%S')}]")
                    batch_start = now_dt

        ok_count = total - failed
        end_dt = datetime.now()
        total_secs = (end_dt - run_start).total_seconds()
        total_dur = f"{total_secs / 3600:.2f}h" if total_secs >= 3600 else f"{total_secs / 60:.1f}m" if total_secs >= 60 else f"{total_secs:.1f}s"
        summary = (
            f"Done. {ok_count} ok, {failed} failed. "
            f"Started: {run_start.strftime('%H:%M:%S')} | "
            f"Ended: {end_dt.strftime('%H:%M:%S')} | "
            f"Total: {total_dur} | Log: {log_path.name}"
        )
        print(f"\n{summary}")
        log_f.write(f"\n{summary}\n")

    if failed_ids:
        lines = [f"{eid} | {reason}" for eid, reason in failed_ids]
        failures_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"Failures written to: {failures_path.name}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
