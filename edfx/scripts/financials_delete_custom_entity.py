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
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))
from project_paths import logs_dir

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)


def parse_entity_ids(raw: str) -> list[str]:
    """Split comma-separated entity ids; strip whitespace; drop empties."""
    return [part.strip() for part in raw.split(",") if part.strip()]


DEFAULT_BASE_URL = "https://api.edfx.moodysanalytics.com"


def delete_custom_entity(
    entity_id: str,
    token: str,
    base_url: str = DEFAULT_BASE_URL,
    cookie: str | None = None,
    timeout: float = 60.0,
) -> requests.Response:
    """Send DELETE .../financials/client/v1/customEntity/{entity_id}."""
    base = base_url.rstrip("/")
    url = f"{base}/financials/client/v1/customEntity/{entity_id}"

    headers: dict[str, str] = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if cookie:
        headers["Cookie"] = cookie

    return requests.delete(url, headers=headers, timeout=timeout)


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
    args = parser.parse_args()

    token = (args.token or "").strip() or (os.environ.get("EDFX_TOKEN") or "").strip()
    if not token:
        parser.error("Provide --token or set the EDFX_TOKEN environment variable.")

    raw_entity = (args.entity_id or "").strip() or (
        os.environ.get("EDFX_DELETE_ENTITY_IDS") or ""
    ).strip()
    entity_ids = parse_entity_ids(raw_entity)
    if not entity_ids:
        parser.error(
            "Provide entity ids via --entity-id or set EDFX_DELETE_ENTITY_IDS in .env."
        )

    _ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _log_path = logs_dir("delete_custom_entity") / f"delete_custom_entity_{_ts}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(_log_path, encoding="utf-8"), logging.StreamHandler()],
    )
    logging.info("delete_custom_entity run start; entity ids=%s", entity_ids)

    cookie_val = (args.cookie or "").strip() or (
        os.environ.get("EDFX_COOKIE") or ""
    ).strip()

    failed = 0
    for i, eid in enumerate(entity_ids, start=1):
        print(f"\n--- [{i}/{len(entity_ids)}] entity-id={eid} ---")
        try:
            resp = delete_custom_entity(
                entity_id=eid,
                token=token,
                base_url=args.base_url,
                cookie=cookie_val or None,
                timeout=args.timeout,
            )
        except requests.RequestException as ex:
            print(f"Request failed: {ex}", file=sys.stderr)
            logging.info("deleted %s -> request failed: %s", eid, ex)
            failed += 1
            continue

        _print_response(resp)
        logging.info("deleted %s -> %s", eid, resp.status_code)
        if not resp.ok:
            failed += 1

    print(f"\nDone. {len(entity_ids) - failed} ok, {failed} failed.")
    logging.info("delete_custom_entity run done; %s ok, %s failed", len(entity_ids) - failed, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
