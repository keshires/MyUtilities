# PD-Aware Pre-Submission Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PD-aware pre-check that classifies each stale entity (post vs skip-with-reason) using its own PD and its peer group's PD, exposed as a standalone report and an opt-in filter on the refresh script — so we stop posting futile `refreshEntities` requests.

**Architecture:** A pure-logic classifier module (`pd_precheck.py`) with a pluggable `PeerGroupPdResolver` (DB-derived fallback now, external API later). A read-only report script and an opt-in `--pd-precheck` flag on the existing refresh script both consume the same classifier. All business logic is pure and unit-tested offline; DB/network is thin and injected.

**Tech Stack:** Python 3.13, asyncpg, pytest (new dev dep), stdlib `dataclasses`/`datetime`.

## Global Constraints

- Run from `Day2Day_Utillites/`; venv at `.\.venv\Scripts\python`.
- Staleness signal is `pd_last_known_date` (never `updated_date`).
- PD-date granularity: **custom = exact 1st-of-month**, **private/public = any day in current month**.
- Postable types: custom, private. **Public is report-only — never posted.**
- Peer-group PD source is external (API) with a `MAX(pd_last_known_date)` over `peerId` DB fallback.
- Tests must run offline (no live DB/API). Resolver and DB fetch are injected.
- Commit only exact paths (branch has concurrent user work — never `git add -A`).
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: Pure classifier core (helpers + `classify` + `StaleRow`)

**Files:**
- Create: `Day2Day_Utillites/pd_precheck.py`
- Create: `Day2Day_Utillites/requirements-dev.txt`
- Test: `Day2Day_Utillites/tests/test_pd_precheck.py`

**Interfaces:**
- Produces: `month_start(today: date) -> date`; `is_pd_current(entity_type: str, pd_date: date|None, ref_month_start: date) -> bool`; `pd_periods_match(entity_type: str, entity_pd: date|None, group_pd: date|None) -> bool`; `Classification(category: str, action: str, reason: str, group_fresh: bool|None)`; `classify(*, entity_type, is_peer_driven: bool, entity_pd: date|None, group_pd: date|None, ref_month_start: date) -> Classification`; `StaleRow(external_id: str, tenant_id: str, pd_last_known_date: date|None, peer_id: str|None, is_peer_driven: bool)`.

- [ ] **Step 1: Add dev dependency + install pytest**

Create `Day2Day_Utillites/requirements-dev.txt`:
```
pytest>=8.0
```
Run: `.\.venv\Scripts\python -m pip install -r requirements-dev.txt`
Expected: pytest installs successfully.

- [ ] **Step 2: Write the failing tests**

Create `Day2Day_Utillites/tests/test_pd_precheck.py`:
```python
from datetime import date
import pd_precheck as p

REF = date(2026, 7, 1)

def test_is_pd_current_true_when_in_current_month():
    assert p.is_pd_current("private", date(2026, 7, 14), REF) is True
    assert p.is_pd_current("custom", date(2026, 7, 1), REF) is True

def test_is_pd_current_false_when_old_or_null():
    assert p.is_pd_current("custom", date(2026, 6, 1), REF) is False
    assert p.is_pd_current("private", None, REF) is False

def test_classify_already_fresh_skips():
    c = p.classify(entity_type="custom", is_peer_driven=False,
                   entity_pd=date(2026, 7, 1), group_pd=None, ref_month_start=REF)
    assert (c.category, c.action) == ("already_fresh", "SKIP")

def test_classify_standalone_posts():
    c = p.classify(entity_type="private", is_peer_driven=False,
                   entity_pd=date(2026, 5, 1), group_pd=None, ref_month_start=REF)
    assert (c.category, c.action) == ("standalone", "POST")

def test_classify_peer_unknown_posts():
    c = p.classify(entity_type="custom", is_peer_driven=True,
                   entity_pd=date(2026, 5, 1), group_pd=None, ref_month_start=REF)
    assert (c.category, c.action) == ("peer_unknown", "POST")

def test_classify_custom_matches_group_exact_skips():
    c = p.classify(entity_type="custom", is_peer_driven=True,
                   entity_pd=date(2026, 6, 1), group_pd=date(2026, 6, 1), ref_month_start=REF)
    assert (c.category, c.action) == ("matches_group", "SKIP")

def test_classify_private_matches_same_month_skips():
    c = p.classify(entity_type="private", is_peer_driven=True,
                   entity_pd=date(2026, 6, 5), group_pd=date(2026, 6, 20), ref_month_start=REF)
    assert (c.category, c.action) == ("matches_group", "SKIP")

def test_classify_peer_lag_group_fresh_posts():
    c = p.classify(entity_type="custom", is_peer_driven=True,
                   entity_pd=date(2026, 6, 1), group_pd=date(2026, 7, 1), ref_month_start=REF)
    assert (c.category, c.action, c.group_fresh) == ("peer_lag", "POST", True)

def test_classify_peer_lag_group_stale_posts():
    c = p.classify(entity_type="custom", is_peer_driven=True,
                   entity_pd=date(2026, 4, 1), group_pd=date(2026, 6, 1), ref_month_start=REF)
    assert (c.category, c.action, c.group_fresh) == ("peer_lag", "POST", False)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.\.venv\Scripts\python -m pytest tests/test_pd_precheck.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pd_precheck'`.

- [ ] **Step 4: Write minimal implementation**

Create `Day2Day_Utillites/pd_precheck.py`:
```python
"""PD-aware pre-check: classify a stale entity as POST (refresh) or SKIP (with reason),
using its own PD date and its peer group's PD date. Pure logic — no DB/network here.

See docs/superpowers/specs/2026-07-15-pd-aware-presubmission-validation-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

POSTABLE_TYPES = {"custom", "private"}


def month_start(today: date) -> date:
    """First day of ``today``'s month — the target period for 'current PD'."""
    return today.replace(day=1)


def is_pd_current(entity_type: str, pd_date: date | None, ref_month_start: date) -> bool:
    """True if ``pd_date`` counts as the current period's PD.

    custom PDs land on the 1st; private/public land any day in the month. Both are
    'current' when the date is in the current month (>= ref_month_start).
    """
    if pd_date is None:
        return False
    return pd_date >= ref_month_start


def pd_periods_match(entity_type: str, entity_pd: date | None, group_pd: date | None) -> bool:
    """True if entity and peer-group PD are the 'same' period for the type.

    custom: exact date equality (both on the 1st). private/public: same calendar month.
    """
    if entity_pd is None or group_pd is None:
        return False
    if entity_type == "custom":
        return entity_pd == group_pd
    return (entity_pd.year, entity_pd.month) == (group_pd.year, group_pd.month)


@dataclass(frozen=True)
class Classification:
    category: str            # already_fresh | standalone | peer_unknown | matches_group | peer_lag
    action: str              # POST | SKIP
    reason: str
    group_fresh: bool | None = None


def classify(
    *,
    entity_type: str,
    is_peer_driven: bool,
    entity_pd: date | None,
    group_pd: date | None,
    ref_month_start: date,
) -> Classification:
    """Decide POST vs SKIP for one stale entity. See spec §4.1 decision table."""
    if is_pd_current(entity_type, entity_pd, ref_month_start):
        return Classification("already_fresh", "SKIP", "entity already has a current PD")
    if not is_peer_driven:
        return Classification("standalone", "POST", "not peer-driven; stale PD")
    if group_pd is None:
        return Classification("peer_unknown", "POST", "peer-driven but peer-group PD unknown")
    if pd_periods_match(entity_type, entity_pd, group_pd):
        return Classification("matches_group", "SKIP", "entity PD matches peer-group PD")
    group_fresh = is_pd_current(entity_type, group_pd, ref_month_start)
    return Classification(
        "peer_lag", "POST", "entity PD older than peer-group PD", group_fresh=group_fresh
    )


@dataclass(frozen=True)
class StaleRow:
    external_id: str
    tenant_id: str
    pd_last_known_date: date | None
    peer_id: str | None
    is_peer_driven: bool
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.\.venv\Scripts\python -m pytest tests/test_pd_precheck.py -v`
Expected: PASS (9 passed).

- [ ] **Step 6: Commit**

```bash
git add Day2Day_Utillites/pd_precheck.py Day2Day_Utillites/requirements-dev.txt Day2Day_Utillites/tests/test_pd_precheck.py
git commit -m "feat(precheck): pure PD classifier + helpers"
```

---

### Task 2: Peer-group PD resolvers + `classify_all`

**Files:**
- Modify: `Day2Day_Utillites/pd_precheck.py` (append resolvers + `classify_all`)
- Test: `Day2Day_Utillites/tests/test_pd_precheck_resolver.py`

**Interfaces:**
- Consumes: `StaleRow`, `classify`, `Classification` from Task 1.
- Produces: `PeerGroupPdResolver.resolve(peer_ids) -> dict[str, date|None]`; `DbMaxPeerGroupPdResolver(fetch)` where `fetch(ids: list[str]) -> list[tuple[str, date|None]]`; `ApiPeerGroupPdResolver(base_url, token_provider=None)` (raises `NotImplementedError`); `classify_all(rows: list[StaleRow], resolver, entity_type, ref_month_start) -> list[tuple[StaleRow, Classification]]`.

- [ ] **Step 1: Write the failing tests**

Create `Day2Day_Utillites/tests/test_pd_precheck_resolver.py`:
```python
from datetime import date
import pytest
import pd_precheck as p

REF = date(2026, 7, 1)

def test_db_resolver_dedupes_and_maps():
    seen = {}
    def fetch(ids):
        seen["ids"] = ids
        return [("A", date(2026, 7, 1)), ("B", None)]
    r = p.DbMaxPeerGroupPdResolver(fetch)
    out = r.resolve(["A", "A", "B", None])
    assert out == {"A": date(2026, 7, 1), "B": None}
    assert sorted(seen["ids"]) == ["A", "B"]  # deduped, no None

def test_api_resolver_not_wired():
    r = p.ApiPeerGroupPdResolver("https://example/api")
    with pytest.raises(NotImplementedError):
        r.resolve(["A"])

def test_classify_all_uses_resolver():
    rows = [
        p.StaleRow("e1", "t1", date(2026, 5, 1), "A", True),   # lags fresh group -> POST
        p.StaleRow("e2", "t1", date(2026, 5, 1), None, False), # standalone -> POST
        p.StaleRow("e3", "t1", date(2026, 6, 1), "B", True),   # matches stale group -> SKIP
    ]
    resolver = p.DbMaxPeerGroupPdResolver(
        lambda ids: [("A", date(2026, 7, 1)), ("B", date(2026, 6, 1))]
    )
    out = p.classify_all(rows, resolver, "custom", REF)
    actions = {r.external_id: c.action for r, c in out}
    assert actions == {"e1": "POST", "e2": "POST", "e3": "SKIP"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python -m pytest tests/test_pd_precheck_resolver.py -v`
Expected: FAIL — `AttributeError: module 'pd_precheck' has no attribute 'DbMaxPeerGroupPdResolver'`.

- [ ] **Step 3: Append implementation to `pd_precheck.py`**

```python
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable


class PeerGroupPdResolver(ABC):
    """Resolves each peer group's authoritative latest PD date."""

    @abstractmethod
    def resolve(self, peer_ids: Iterable[str]) -> dict[str, date | None]:
        ...


class DbMaxPeerGroupPdResolver(PeerGroupPdResolver):
    """Fallback resolver: group PD date = MAX(pd_last_known_date) over peerId.

    ``fetch(ids)`` returns ``[(peer_id, max_pd_date), ...]`` — injected so this is
    unit-testable offline and swappable for a live asyncpg query in the scripts.
    """

    def __init__(self, fetch: Callable[[list[str]], list[tuple[str, date | None]]]) -> None:
        self._fetch = fetch

    def resolve(self, peer_ids: Iterable[str]) -> dict[str, date | None]:
        ids = [pid for pid in dict.fromkeys(peer_ids) if pid]
        if not ids:
            return {}
        return {pid: pd for pid, pd in self._fetch(ids)}


class ApiPeerGroupPdResolver(PeerGroupPdResolver):
    """Authoritative external-source resolver. Endpoint/auth not wired yet (spec §8)."""

    def __init__(self, base_url: str, token_provider: Callable[[], str] | None = None) -> None:
        self.base_url = base_url
        self.token_provider = token_provider

    def resolve(self, peer_ids: Iterable[str]) -> dict[str, date | None]:
        raise NotImplementedError(
            "External peer-group PD endpoint not wired yet; use DbMaxPeerGroupPdResolver."
        )


def classify_all(
    rows: list["StaleRow"],
    resolver: PeerGroupPdResolver,
    entity_type: str,
    ref_month_start: date,
) -> list[tuple["StaleRow", Classification]]:
    """Classify every row, batch-resolving peer-group PD dates once."""
    group = resolver.resolve([r.peer_id for r in rows if r.peer_id]) if rows else {}
    return [
        (
            r,
            classify(
                entity_type=entity_type,
                is_peer_driven=r.is_peer_driven,
                entity_pd=r.pd_last_known_date,
                group_pd=(group.get(r.peer_id) if r.peer_id else None),
                ref_month_start=ref_month_start,
            ),
        )
        for r in rows
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python -m pytest tests/test_pd_precheck_resolver.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add Day2Day_Utillites/pd_precheck.py Day2Day_Utillites/tests/test_pd_precheck_resolver.py
git commit -m "feat(precheck): peer-group resolvers + classify_all"
```

---

### Task 3: `validate_pd_precheck.py` report script

**Files:**
- Create: `Day2Day_Utillites/validate_pd_precheck.py`
- Test: `Day2Day_Utillites/tests/test_validate_pd_precheck.py`

**Interfaces:**
- Consumes: `StaleRow`, `classify_all`, `DbMaxPeerGroupPdResolver` from Tasks 1–2; `project_paths.output_dir`, `project_paths.logs_dir`.
- Produces: `summarize(classified: list[tuple[StaleRow, Classification]], entity_type: str) -> dict`.

- [ ] **Step 1: Write the failing test**

Create `Day2Day_Utillites/tests/test_validate_pd_precheck.py`:
```python
from datetime import date
import pd_precheck as p
import validate_pd_precheck as v

REF = date(2026, 7, 1)

def test_summarize_counts_and_expected_refresh():
    rows = [
        p.StaleRow("e1", "t1", date(2026, 5, 1), None, False),  # standalone POST
        p.StaleRow("e2", "t1", date(2026, 6, 1), "B", True),    # matches stale group SKIP
        p.StaleRow("e3", "t2", date(2026, 5, 1), "A", True),    # peer_lag fresh POST
    ]
    resolver = p.DbMaxPeerGroupPdResolver(
        lambda ids: [("A", date(2026, 7, 1)), ("B", date(2026, 6, 1))]
    )
    classified = p.classify_all(rows, resolver, "custom", REF)
    s = v.summarize(classified, "custom")
    assert s["stale_found"] == 3
    assert s["expected_to_refresh"] == 2
    assert s["by_category"]["matches_group"] == 1
    assert s["by_tenant"]["t1"] == 2

def test_summarize_public_expected_zero():
    rows = [p.StaleRow("e1", "t1", date(2026, 5, 1), None, False)]
    classified = p.classify_all(rows, p.DbMaxPeerGroupPdResolver(lambda ids: []), "public", REF)
    s = v.summarize(classified, "public")
    assert s["expected_to_refresh"] == 0
    assert s["stale_found"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python -m pytest tests/test_validate_pd_precheck.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'validate_pd_precheck'`.

- [ ] **Step 3: Write minimal implementation**

Create `Day2Day_Utillites/validate_pd_precheck.py`:
```python
"""Read-only PD-aware pre-check report. For a chosen --entity-type, classify every
stale entity (by pd_last_known_date) as POST/SKIP with reason, using the peer-group
resolver, and write a categorized CSV + summary JSON. Never posts anything.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

import pd_precheck as pc
from project_paths import logs_dir, output_dir

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_EXCLUDED = ("001aJ00000Cwqc2QAB",)
CUSTOM_ID = {"custom": "custom_id IS NOT NULL", "private": "custom_id IS NULL"}


def summarize(classified: list[tuple[pc.StaleRow, pc.Classification]], entity_type: str) -> dict:
    cats = Counter(c.category for _, c in classified)
    by_tenant: Counter = Counter(r.tenant_id for _, _ in [(r, c) for r, c in classified])
    post = sum(1 for _, c in classified if c.action == "POST")
    skip = sum(1 for _, c in classified if c.action == "SKIP")
    return {
        "entity_type": entity_type,
        "stale_found": len(classified),
        "expected_to_refresh": 0 if entity_type not in pc.POSTABLE_TYPES else post,
        "post": post,
        "skip": skip,
        "by_category": dict(cats),
        "by_tenant": dict(by_tenant),
    }


def _excluded() -> list[str]:
    raw = (os.getenv("STALE_REFRESH_EXCLUDED_TENANTS") or "").strip()
    return [x.strip() for x in raw.split(",") if x.strip()] or list(DEFAULT_EXCLUDED)


def _stale_query(entity_type: str) -> str:
    data_type = "e.data_type = 'Private'" if entity_type in ("custom", "private") else "e.data_type <> 'Private'"
    custom_clause = f"AND {CUSTOM_ID[entity_type]}" if entity_type in CUSTOM_ID else ""
    return f"""
    SELECT e.external_id, e.tenant_id, e.pd_last_known_date,
           e.entity_data->>'peerId' AS peer_id,
           COALESCE(e.entity_data->>'isPeerDriven','') AS is_peer_driven
    FROM public.entity e
    WHERE {data_type} {custom_clause}
      AND e.external_id IS NOT NULL
      AND e.tenant_id <> ALL($2::text[])
      AND (NULLIF(e.entity_data->>'financialStmtDate','') IS NULL
           OR NULLIF(e.entity_data->>'financialStmtDate','')::timestamp >= (NOW()-INTERVAL '3 years'))
      AND (e.pd_last_known_date IS NULL OR e.pd_last_known_date < $1::timestamp)
    """


async def _pg():
    return await asyncpg.connect(
        host=os.environ["TESSERA_POSTGRES_HOST"], port=int(os.getenv("TESSERA_POSTGRES_PORT", "5432")),
        database=os.environ["TESSERA_POSTGRES_DB"], user=os.environ["TESSERA_POSTGRES_USER"],
        password=os.environ["TESSERA_POSTGRES_PASSWORD"], ssl="prefer",
    )


async def _fetch_rows(entity_type: str, ref: date, excluded: list[str]) -> list[pc.StaleRow]:
    conn = await _pg()
    try:
        rows = await conn.fetch(_stale_query(entity_type), datetime.combine(ref, datetime.min.time()), excluded)
    finally:
        await conn.close()
    return [
        pc.StaleRow(str(r["external_id"]), str(r["tenant_id"]), r["pd_last_known_date"],
                    r["peer_id"], r["is_peer_driven"] == "true")
        for r in rows
    ]


def _db_resolver() -> pc.DbMaxPeerGroupPdResolver:
    def fetch(ids: list[str]) -> list[tuple[str, date | None]]:
        async def run():
            conn = await _pg()
            try:
                q = """SELECT entity_data->>'peerId' pid, MAX(pd_last_known_date) mx
                       FROM public.entity WHERE entity_data->>'peerId' = ANY($1::text[])
                       GROUP BY 1"""
                return await conn.fetch(q, ids)
            finally:
                await conn.close()
        return [(str(r["pid"]), r["mx"]) for r in asyncio.run(run())]
    return pc.DbMaxPeerGroupPdResolver(fetch)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--entity-type", required=True, choices=["custom", "private", "public"])
    ap.add_argument("--date-filter", default=None, help="Stale cutoff YYYY-MM-DD (default 1st of month).")
    args = ap.parse_args(argv)

    ref = (datetime.strptime(args.date_filter, "%Y-%m-%d").date()
           if args.date_filter else pc.month_start(date.today()))
    excluded = _excluded()
    rows = asyncio.run(_fetch_rows(args.entity_type, ref, excluded))
    classified = pc.classify_all(rows, _db_resolver(), args.entity_type, ref)
    summary = summarize(classified, args.entity_type)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_csv = output_dir("validate_pd_precheck") / f"pd_precheck_{args.entity_type}_{ts}.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["external_id", "tenant_id", "pd_last_known_date", "peer_id",
                    "is_peer_driven", "category", "action", "reason", "group_fresh"])
        for r, c in classified:
            w.writerow([r.external_id, r.tenant_id, r.pd_last_known_date, r.peer_id,
                        r.is_peer_driven, c.category, c.action, c.reason, c.group_fresh])
    summary_path = logs_dir("validate_pd_precheck") / f"pd_precheck_{args.entity_type}_{ts}.summary.json"
    summary_path.write_text(json.dumps({"summary": summary, "ref": ref.isoformat(),
                                        "output_csv": str(out_csv)}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"\nWrote {summary['stale_found']} rows to {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python -m pytest tests/test_validate_pd_precheck.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add Day2Day_Utillites/validate_pd_precheck.py Day2Day_Utillites/tests/test_validate_pd_precheck.py
git commit -m "feat(precheck): read-only PD pre-check report script"
```

---

### Task 4: `--pd-precheck` filter on the refresh script

**Files:**
- Modify: `Day2Day_Utillites/refresh_stale_non_public_entities.py` (add flag + `precheck_post_ids` use)
- Modify: `Day2Day_Utillites/pd_precheck.py` (add `post_ids` helper)
- Test: `Day2Day_Utillites/tests/test_refresh_precheck.py`

**Interfaces:**
- Consumes: `classify_all`, `StaleRow`, resolvers from Tasks 1–2.
- Produces: `pd_precheck.post_ids(rows, resolver, entity_type, ref_month_start) -> set[str]`.

- [ ] **Step 1: Write the failing test**

Create `Day2Day_Utillites/tests/test_refresh_precheck.py`:
```python
from datetime import date
import pd_precheck as p

REF = date(2026, 7, 1)

def test_post_ids_keeps_only_post_actions():
    rows = [
        p.StaleRow("keep1", "t1", date(2026, 5, 1), None, False),   # standalone POST
        p.StaleRow("skip1", "t1", date(2026, 6, 1), "B", True),     # matches stale group SKIP
        p.StaleRow("keep2", "t1", date(2026, 5, 1), "A", True),     # peer_lag POST
    ]
    resolver = p.DbMaxPeerGroupPdResolver(
        lambda ids: [("A", date(2026, 7, 1)), ("B", date(2026, 6, 1))]
    )
    ids = p.post_ids(rows, resolver, "custom", REF)
    assert ids == {"keep1", "keep2"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python -m pytest tests/test_refresh_precheck.py -v`
Expected: FAIL — `AttributeError: module 'pd_precheck' has no attribute 'post_ids'`.

- [ ] **Step 3: Add `post_ids` to `pd_precheck.py`**

```python
def post_ids(rows, resolver, entity_type, ref_month_start) -> set[str]:
    """external_ids whose classification action is POST (used by the refresh pre-filter)."""
    return {r.external_id for r, c in classify_all(rows, resolver, entity_type, ref_month_start)
            if c.action == "POST"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python -m pytest tests/test_refresh_precheck.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Wire the flag into `refresh_stale_non_public_entities.py`**

In `parse_args` (near the other flags, ~line 1300), add:
```python
    parser.add_argument(
        "--pd-precheck",
        action="store_true",
        help=(
            "Before posting, classify each stale entity and submit only genuine "
            "candidates (skip already-fresh, peer-group-matched). Requires "
            "--stale-date-column pd_last_known_date."
        ),
    )
```
In `main`, after `excluded = excluded_tenant_ids()` and before scope processing, add a
pre-filter that computes the allowed external_ids once and stores them for the batch
iterator (only when the flag is set). Add this block:
```python
    precheck_ids: set[str] | None = None
    if args.pd_precheck:
        if stale_date_column != "pd_last_known_date":
            raise SystemExit("--pd-precheck requires --stale-date-column pd_last_known_date")
        import pd_precheck as pc
        ref_ms = pc.month_start(date.today())

        async def _fetch_precheck_rows() -> list[pc.StaleRow]:
            conn = await pg_connect()
            try:
                q = f"""SELECT e.external_id, e.tenant_id, e.pd_last_known_date,
                               e.entity_data->>'peerId' AS peer_id,
                               COALESCE(e.entity_data->>'isPeerDriven','') AS ipd
                        FROM public.entity e
                        WHERE data_type='Private' AND {entity_mode.custom_id_clause}
                          AND external_id IS NOT NULL AND {tenant_clause(tenant_id=tenant_id)}
                          {financial_stmt_clause(financial_max_age_years)}
                          {stale_date_clause(stale_date_column)}"""
                params = [datetime.combine(date_filter, datetime.min.time()),
                          tenant_id if tenant_id else excluded]
                rows = await conn.fetch(q, *params)
            finally:
                await conn.close()
            return [pc.StaleRow(str(r["external_id"]), str(r["tenant_id"]),
                                r["pd_last_known_date"], r["peer_id"], r["ipd"] == "true")
                    for r in rows]

        def _fetch_group(ids: list[str]):
            async def run():
                conn = await pg_connect()
                try:
                    return await conn.fetch(
                        "SELECT entity_data->>'peerId' pid, MAX(pd_last_known_date) mx "
                        "FROM public.entity WHERE entity_data->>'peerId' = ANY($1::text[]) GROUP BY 1", ids)
                finally:
                    await conn.close()
            return [(str(r["pid"]), r["mx"]) for r in asyncio.run(run())]

        rows = asyncio.run(_fetch_precheck_rows())
        precheck_ids = pc.post_ids(rows, pc.DbMaxPeerGroupPdResolver(_fetch_group),
                                   entity_mode.name, ref_ms)
        logger.info("Pre-check: %s of %s stale entities will be posted (%s skipped)",
                    len(precheck_ids), len(rows), len(rows) - len(precheck_ids))
```
Then in `iter_stale_batches`, accept an optional `allowed_ids: set[str] | None = None` parameter and, inside the `async for row in cursor:` loop, skip rows not allowed:
```python
                external_id = row["external_id"]
                if external_id is None:
                    continue
                if allowed_ids is not None and str(external_id) not in allowed_ids:
                    continue
```
Pass `allowed_ids=precheck_ids` from `process_batches` down to `iter_stale_batches` (add the
param to `process_batches` signature and both `iter_stale_batches(...)` call sites), and pass
`precheck_ids` when calling `process_batches` inside `execute_refresh` (thread it through the
`execute_refresh` params like the other options). Record it in the run summary:
```python
        "pd_precheck": args.pd_precheck,
```

- [ ] **Step 6: Run the precheck unit test + full suite**

Run: `.\.venv\Scripts\python -m pytest tests/ -v`
Expected: PASS (all tests green).

- [ ] **Step 7: Smoke-test the flag offline (dry-run guard only)**

Run: `.\.venv\Scripts\python refresh_stale_non_public_entities.py --entity-type custom --one-per-request --pd-precheck --dry-run 2>&1 | Select-String "requires|Pre-check|PLAN" | Select-Object -First 5`
Expected: either the guard message (if column not set) or, with `--stale-date-column pd_last_known_date`, a "Pre-check: N of M ... will be posted" line then the dry-run plan. (Needs DB; if no DB, confirm the guard/arg parsing at least.)

- [ ] **Step 8: Commit**

```bash
git add Day2Day_Utillites/refresh_stale_non_public_entities.py Day2Day_Utillites/pd_precheck.py Day2Day_Utillites/tests/test_refresh_precheck.py
git commit -m "feat(refresh): --pd-precheck pre-filter (post only genuine candidates)"
```

---

### Task 5: Catalog entry + runbook/skill note + final verification

**Files:**
- Modify: `Day2Day_Utillites/utilities.yaml` (add `validate-pd-precheck`)
- Modify: `Day2Day_Utillites/Docs/monthly-stale-refresh-runbook.md` (add pre-check step)
- Modify: `.claude/skills/stale-entity-refresh/SKILL.md` (mention `--pd-precheck` / report)

**Interfaces:** none (docs + catalog only).

- [ ] **Step 1: Add the catalog entry** to `utilities.yaml` under a suitable category (`stale-entity-refresh`):
```yaml
  - id: validate-pd-precheck
    name: PD Pre-Check Report
    script: validate_pd_precheck.py
    category: stale-entity-refresh
    purpose: "Classify stale entities (by pd_last_known_date) as POST/SKIP using entity + peer-group PD, to avoid futile refreshEntities posts. Read-only."
    invocation: cli
    args:
      - flag: --entity-type
        required: true
        choices: [custom, private, public]
        help: "custom, private, or public (public is report-only)."
      - flag: --date-filter
        help: "Stale cutoff YYYY-MM-DD. Default first of current month."
    env_required: [TESSERA_POSTGRES_HOST, TESSERA_POSTGRES_PORT, TESSERA_POSTGRES_DB, TESSERA_POSTGRES_USER, TESSERA_POSTGRES_PASSWORD]
    outputs:
      output_glob: "validate_pd_precheck/*"
      summary_suffix: ".summary.json"
    docs: ["docs/superpowers/specs/2026-07-15-pd-aware-presubmission-validation-design.md"]
    safety: "Read-only against prod Postgres. Never posts."
```

- [ ] **Step 2: Add a pre-check note** to the runbook (`monthly-stale-refresh-runbook.md`), after step 1:
```markdown
### 1b. (Optional) PD pre-check report — see what's worth refreshing
`.\.venv\Scripts\python validate_pd_precheck.py --entity-type custom`
Classifies the stale set POST vs SKIP (already-fresh / peer-group-matched). Use
`--pd-precheck` on the refresh command to post only the POST candidates.
```

- [ ] **Step 3: Add one line** to `SKILL.md` under the monthly-run section:
```markdown
- Optional pre-filter: add `--pd-precheck` to the refresh (with `--stale-date-column pd_last_known_date`)
  to skip futile posts; `validate_pd_precheck.py --entity-type <t>` reports the POST/SKIP split.
```

- [ ] **Step 4: Full verification**

Run: `.\.venv\Scripts\python -m pytest tests/ -v`
Expected: PASS (all tests, ~15).

- [ ] **Step 5: Commit**

```bash
git add Day2Day_Utillites/utilities.yaml Day2Day_Utillites/Docs/monthly-stale-refresh-runbook.md .claude/skills/stale-entity-refresh/SKILL.md
git commit -m "docs(precheck): catalog entry + runbook/skill notes for PD pre-check"
```

---

## Self-Review

- **Spec coverage:** §4.1 classifier → Task 1; §4.1 resolvers → Task 2; §4.2 report → Task 3; §4.3 refresh flag → Task 4; catalog/docs → Task 5; public report-only → Tasks 3/5 (public rejected for refresh, `expected_to_refresh=0`). Error handling (§6): resolver fallback is the DB resolver by default; null peerId/pd → `peer_unknown`/stale (covered in classifier tests).
- **Placeholder scan:** none — all steps have concrete code/commands.
- **Type consistency:** `StaleRow`, `Classification`, `classify`, `classify_all`, `post_ids`, `DbMaxPeerGroupPdResolver(fetch)` signatures match across Tasks 1–4.
- **Deferred (spec §8):** `ApiPeerGroupPdResolver` stays a stub until the external endpoint is supplied; DB fallback is the default resolver everywhere.
