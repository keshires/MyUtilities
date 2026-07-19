# Portfolio KPI Refresh Reports Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the portfolio_kpi_update_log report set fast (extract-once / aggregate-many via session TEMP tables), add three new report shapes plus two 2D pivots, and let every report run against CI/QA/STG via `--env`.

**Architecture:** Extend the existing read-only runner [`portfolio_kpi_metrics_postgres.py`](../../../Day2Day_Utillites/portfolio_kpi_metrics_postgres.py) and its SQL file [`portfolio-kpi-metrics.sql`](../../../Day2Day_Utillites/Docs/portfolio-kpi-metrics.sql). A new `-- SETUP: build_temp` SQL block materializes two session TEMP tables (`tmp_kpi_window`, `tmp_kpi_entity`) once per run — extracting `entity_refresh_message->>'source'` into a plain column and pre-`unnest`ing the entity array — then every report reads from the temp tables. Pivots are built in Python. Env selection loads `.env.<env>` ahead of base `.env`.

**Tech Stack:** Python 3 (stdlib `argparse`, `csv`, `re`), `asyncpg`, `python-dotenv`, `pytest` (tests), PostgreSQL (range-partitioned table).

## Global Constraints

- Tool is **read-only** against the DB. No `INSERT`/`UPDATE`/`DELETE`/DDL on base tables. TEMP tables only.
- Run everything from the `Day2Day_Utillites/` folder using its venv: `.\.venv\Scripts\python` (Windows) — the plan's commands assume cwd = `Day2Day_Utillites`.
- Tests use **pytest** (installed, v9.1.1 — the established convention: plain `assert` functions importing top-level modules, e.g. `import portfolio_kpi_metrics_postgres as mod`). Run from `Day2Day_Utillites` as `.\.venv\Scripts\python -m pytest tests/<file>.py -v` (the `-m pytest` form puts the project dir on `sys.path` so top-level modules import). **Do NOT create `tests/__init__.py`** — the existing suite relies on rootdir import mode; a package marker would break it.
- Preserve existing `-- REPORT:` marker names already in the SQL file (DBeaver users reference them). New reports add new markers.
- Window filter must stay `message_created_at >= start AND message_created_at < end` (partition pruning). `--start` inclusive, `--end` exclusive.
- `--source`, when set, scopes the whole run (applied when building `tmp_kpi_window`).
- Timestamps are naive `timestamp` (treated as UTC), matching existing code.
- Never commit real secrets. Per-env `.env.<env>` files stay gitignored; only `*.example` templates are tracked.
- Non-prod DB credentials are NOT available during implementation. DB-dependent end-to-end checks are documented as manual verification steps to run once the operator supplies `.env.qa` etc.

## Report registry (authoritative — refines the spec's table)

CLI `--report` alias → SQL `-- REPORT:` marker:

| CLI alias | SQL marker | Source |
|-----------|-----------|--------|
| `hourly` | `hourly_totals` | existing (optimized) |
| `hourly_by_status` | `hourly_by_status` | existing (optimized) |
| `status` | `status_summary` | existing (optimized) |
| `slow` | `slow_global` | existing (optimized) |
| `slow_by_source` | `slow_by_source` | existing (optimized) |
| `source_update_totals` | `source_update_totals` | existing (optimized) |
| `entity_counts` | `triggering_entity_counts` | existing (optimized; by entity_id+source) |
| `entities_by_day` | `triggering_entity_counts_by_day` | existing (optimized) |
| `portfolio_updates_by_source` | `portfolio_updates_by_source` | existing (optimized) |
| `daily` | `daily_totals_source` | new marker |
| `entity_source_totals` | `entity_source_totals` | new marker (by source only) |
| `portfolio_update_totals` | `portfolio_update_totals` | new marker |
| `entities_by_day_source_status` | `entities_by_day_source_status` | **new (#1)** |
| `portfolios_by_day_source_status` | `portfolios_by_day_source_status` | **new (#2)** |
| `entity_by_source` | `entity_by_source` | **new pivot (#3a)** |
| `portfolio_entity_source` | `portfolio_entity_source` | **new pivot (#3b)** |
| `all` | (runs the aggregate set below) | — |

`all` marker set: `daily_totals_source, hourly_totals, hourly_by_status, status_summary, source_update_totals, triggering_entity_counts, triggering_entity_counts_by_day, entities_by_day_source_status, portfolios_by_day_source_status` (excludes the two slow-detail reports and the two large pivots).

Pivot specs (`marker → (index_cols, pivot_col, value_col)`):
- `entity_by_source → (["entity_id"], "source", "refresh_count")`
- `portfolio_entity_source → (["portfolio_id", "entity_id"], "source", "refresh_count")`

---

### Task 1: Environment selection (`--env` + `load_env`)

**Files:**
- Modify: `Day2Day_Utillites/portfolio_kpi_metrics_postgres.py`
- Test: `Day2Day_Utillites/tests/test_env_loading.py`

**Interfaces:**
- Produces: `load_env(env: str | None, root: Path = PROJECT_ROOT) -> list[Path]` — loads `.env.<env>` then base `.env` with `override=False` (so OS env wins, then env-file, then base). Returns the list of files actually loaded. Missing `.env.<env>` prints a warning to stderr and is skipped.

Do NOT create `tests/__init__.py` — pytest collects `tests/` by rootdir import mode; a package marker would break the existing suite.

- [ ] **Step 1: Write the failing test**

Create `Day2Day_Utillites/tests/test_env_loading.py` (pytest style, matching the existing suite):

```python
import os
from pathlib import Path

import pytest

import portfolio_kpi_metrics_postgres as mod

_KEYS = ("KPI_T_OSWIN", "KPI_T_ENVFILE", "KPI_T_BASE")


@pytest.fixture(autouse=True)
def _clean_env():
    """Snapshot/restore the vars these tests touch (load_dotenv mutates os.environ)."""
    saved = {k: os.environ.get(k) for k in _KEYS}
    for k in _KEYS:
        os.environ.pop(k, None)
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_precedence_os_then_envfile_then_base(tmp_path):
    (tmp_path / ".env.qa").write_text(
        "KPI_T_OSWIN=fromfile\nKPI_T_ENVFILE=fromqa\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text(
        "KPI_T_ENVFILE=frombase\nKPI_T_BASE=frombase\n", encoding="utf-8"
    )
    os.environ["KPI_T_OSWIN"] = "fromos"

    loaded = mod.load_env("qa", root=tmp_path)

    assert os.environ["KPI_T_OSWIN"] == "fromos"      # OS wins
    assert os.environ["KPI_T_ENVFILE"] == "fromqa"    # env-file beats base
    assert os.environ["KPI_T_BASE"] == "frombase"     # base fills gap
    assert [p.name for p in loaded] == [".env.qa", ".env"]


def test_missing_env_file_is_not_fatal(tmp_path):
    (tmp_path / ".env").write_text("KPI_T_BASE=frombase\n", encoding="utf-8")
    loaded = mod.load_env("nope", root=tmp_path)  # .env.nope does not exist
    assert [p.name for p in loaded] == [".env"]
    assert os.environ["KPI_T_BASE"] == "frombase"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python -m pytest tests/test_env_loading.py -v`
Expected: FAIL — `AttributeError: module 'portfolio_kpi_metrics_postgres' has no attribute 'load_env'`.

- [ ] **Step 3: Implement `load_env` and drop the old loader import**

In `Day2Day_Utillites/portfolio_kpi_metrics_postgres.py`, change the import line:

```python
from run_portfolio_kpis_postgres import PostgresSettings, _load_dotenv_from_project_root
```
to:
```python
from run_portfolio_kpis_postgres import PostgresSettings
```

Also update the one call site in `main()` so the CLI keeps working after this task (Task 6 later replaces this whole `main()` body). Change the line inside `main()`:
```python
    _load_dotenv_from_project_root()
```
to:
```python
    load_env(None)
```

Add this function just below the imports (after the `from run_portfolio_kpis_postgres import PostgresSettings` line):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python -m pytest tests/test_env_loading.py -v`
Expected: PASS (2 tests in `test_env_loading`).

- [ ] **Step 5: Commit**

```bash
git add Day2Day_Utillites/portfolio_kpi_metrics_postgres.py Day2Day_Utillites/tests/test_env_loading.py
git commit -m "feat(kpi-metrics): add --env-aware .env loader (load_env)"
```

---

### Task 2: Python pivot helper (`pivot_rows`)

**Files:**
- Modify: `Day2Day_Utillites/portfolio_kpi_metrics_postgres.py`
- Test: `Day2Day_Utillites/tests/test_pivot_rows.py`

**Interfaces:**
- Produces: `pivot_rows(rows: list[dict], index_cols: list[str], pivot_col: str, value_col: str, top: int | None = None) -> list[dict[str, Any]]` — wide rows: each dict is `{index cols…, <one key per distinct pivot value, sorted, zero-filled>…, "total": int}`, sorted by `total` DESC then index cols ASC, truncated to `top` when given.

- [ ] **Step 1: Write the failing test**

Create `Day2Day_Utillites/tests/test_pivot_rows.py`:

```python
from portfolio_kpi_metrics_postgres import pivot_rows

LONG = [
    {"entity_id": "E1", "source": "Custom Financials", "refresh_count": 3},
    {"entity_id": "E1", "source": "EDF-X", "refresh_count": 2},
    {"entity_id": "E2", "source": "Custom Financials", "refresh_count": 10},
]


def test_wide_shape_zero_fill_and_total():
    wide = pivot_rows(LONG, ["entity_id"], "source", "refresh_count")
    # E2 has the higher total (10) so it sorts first.
    assert wide[0]["entity_id"] == "E2"
    assert wide[0]["Custom Financials"] == 10
    assert wide[0]["EDF-X"] == 0      # zero-filled
    assert wide[0]["total"] == 10
    assert wide[1]["entity_id"] == "E1"
    assert wide[1]["total"] == 5
    # Column order: index col, then sorted sources, then total.
    assert list(wide[0].keys()) == ["entity_id", "Custom Financials", "EDF-X", "total"]


def test_top_truncates():
    wide = pivot_rows(LONG, ["entity_id"], "source", "refresh_count", top=1)
    assert len(wide) == 1
    assert wide[0]["entity_id"] == "E2"


def test_multi_index():
    rows = [
        {"portfolio_id": 1, "entity_id": "E1", "source": "A", "refresh_count": 1},
        {"portfolio_id": 1, "entity_id": "E1", "source": "B", "refresh_count": 4},
        {"portfolio_id": 2, "entity_id": "E9", "source": "A", "refresh_count": 2},
    ]
    wide = pivot_rows(rows, ["portfolio_id", "entity_id"], "source", "refresh_count")
    assert list(wide[0].keys()) == ["portfolio_id", "entity_id", "A", "B", "total"]
    assert wide[0]["portfolio_id"] == 1
    assert wide[0]["total"] == 5


def test_empty():
    assert pivot_rows([], ["entity_id"], "source", "refresh_count") == []


def test_numeric_index_tiebreak_orders_naturally():
    # Equal totals must break ties by natural (numeric) index order, not string order.
    rows = [
        {"portfolio_id": 10, "source": "A", "refresh_count": 5},
        {"portfolio_id": 2, "source": "A", "refresh_count": 5},
    ]
    wide = pivot_rows(rows, ["portfolio_id"], "source", "refresh_count")
    assert [r["portfolio_id"] for r in wide] == [2, 10]


def test_sums_duplicate_index_pivot_pairs():
    rows = [
        {"entity_id": "E1", "source": "A", "refresh_count": 3},
        {"entity_id": "E1", "source": "A", "refresh_count": 4},
    ]
    wide = pivot_rows(rows, ["entity_id"], "source", "refresh_count")
    assert len(wide) == 1
    assert wide[0]["A"] == 7
    assert wide[0]["total"] == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python -m pytest tests/test_pivot_rows.py -v`
Expected: FAIL — `ImportError: cannot import name 'pivot_rows'`.

- [ ] **Step 3: Implement `pivot_rows`**

Add to `Day2Day_Utillites/portfolio_kpi_metrics_postgres.py` (near the other helpers, e.g. above `print_table`):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python -m pytest tests/test_pivot_rows.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add Day2Day_Utillites/portfolio_kpi_metrics_postgres.py Day2Day_Utillites/tests/test_pivot_rows.py
git commit -m "feat(kpi-metrics): add pivot_rows helper for 2D report output"
```

---

### Task 3: Report registry + `resolve_reports`

**Files:**
- Modify: `Day2Day_Utillites/portfolio_kpi_metrics_postgres.py`
- Test: `Day2Day_Utillites/tests/test_report_registry.py`

**Interfaces:**
- Produces: module constants `REPORT_ALIASES: dict[str,str]`, `REPORT_CHOICES: tuple[str,...]`, `ALL_REPORT_KEYS: tuple[str,...]`, `PIVOT_SPECS: dict[str, tuple[list[str], str, str]]`; and `resolve_reports(report_arg: str) -> list[str]` returning SQL marker names.

- [ ] **Step 1: Write the failing test**

Create `Day2Day_Utillites/tests/test_report_registry.py`:

```python
import pytest

import portfolio_kpi_metrics_postgres as mod


def test_all_expands_to_marker_set():
    keys = mod.resolve_reports("all")
    assert "entities_by_day_source_status" in keys
    assert "portfolios_by_day_source_status" in keys
    assert "slow_global" not in keys        # slow excluded from all
    assert "entity_by_source" not in keys   # pivots excluded from all


def test_alias_maps_to_marker():
    assert mod.resolve_reports("daily") == ["daily_totals_source"]
    assert mod.resolve_reports("status") == ["status_summary"]
    assert mod.resolve_reports("entities_by_day") == ["triggering_entity_counts_by_day"]


def test_new_reports_resolve():
    for alias in (
        "entities_by_day_source_status",
        "portfolios_by_day_source_status",
        "entity_by_source",
        "portfolio_entity_source",
    ):
        assert mod.resolve_reports(alias) == [alias]


def test_pivot_specs_shape():
    assert mod.PIVOT_SPECS["entity_by_source"] == (["entity_id"], "source", "refresh_count")
    assert mod.PIVOT_SPECS["portfolio_entity_source"] == (
        ["portfolio_id", "entity_id"], "source", "refresh_count"
    )


def test_unknown_report_raises():
    with pytest.raises(SystemExit):
        mod.resolve_reports("does_not_exist")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python -m pytest tests/test_report_registry.py -v`
Expected: FAIL — assertions about new aliases / `PIVOT_SPECS` not defined.

- [ ] **Step 3: Replace the registry constants and `resolve_reports`**

In `Day2Day_Utillites/portfolio_kpi_metrics_postgres.py`, replace the existing `REPORT_CHOICES`, `REPORT_ALIASES`, and `ALL_REPORT_KEYS` blocks with:

```python
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

ALL_REPORT_KEYS = (
    "daily_totals_source",
    "hourly_totals",
    "hourly_by_status",
    "status_summary",
    "source_update_totals",
    "triggering_entity_counts",
    "triggering_entity_counts_by_day",
    "entities_by_day_source_status",
    "portfolios_by_day_source_status",
)

# marker -> (index_cols, pivot_col, value_col) for Python-side pivots.
PIVOT_SPECS: dict[str, tuple[list[str], str, str]] = {
    "entity_by_source": (["entity_id"], "source", "refresh_count"),
    "portfolio_entity_source": (["portfolio_id", "entity_id"], "source", "refresh_count"),
}
```

`resolve_reports` already exists and reads `REPORT_ALIASES`/`ALL_REPORT_KEYS`/`REPORT_CHOICES`; leave its body as-is (it will pick up the new constants automatically). Confirm its current body matches:

```python
def resolve_reports(report_arg: str) -> list[str]:
    if report_arg == "all":
        return list(ALL_REPORT_KEYS)
    key = REPORT_ALIASES.get(report_arg)
    if key is None:
        raise SystemExit(
            f"Unknown --report {report_arg!r}. Choose: {', '.join(REPORT_CHOICES)}"
        )
    return [key]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python -m pytest tests/test_report_registry.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add Day2Day_Utillites/portfolio_kpi_metrics_postgres.py Day2Day_Utillites/tests/test_report_registry.py
git commit -m "feat(kpi-metrics): expand report registry + pivot specs"
```

---

### Task 4: SQL section parser (`load_sql_sections`)

**Files:**
- Modify: `Day2Day_Utillites/portfolio_kpi_metrics_postgres.py`
- Test: `Day2Day_Utillites/tests/test_sql_sections.py`

**Interfaces:**
- Produces: `load_sql_sections(text: str) -> tuple[str, dict[str, str]]` — returns `(setup_sql, reports)` where `setup_sql` is the concatenation of `-- SETUP: <name>` block bodies (may be empty string) and `reports` maps each `-- REPORT: <name>` to its body (each ensured to end with `;`). Replaces the old `load_sql_reports`.
- Consumes (later tasks): `run_reports` will call this instead of `load_sql_reports`.

- [ ] **Step 1: Write the failing test**

Create `Day2Day_Utillites/tests/test_sql_sections.py`:

```python
import pytest

from portfolio_kpi_metrics_postgres import load_sql_sections

SAMPLE = """\
-- header comment
SELECT set_config('x','y',false);

-- SETUP: build_temp
DROP TABLE IF EXISTS tmp_kpi_window;
CREATE TEMP TABLE tmp_kpi_window AS SELECT 1 AS a;

-- REPORT: status_summary
SELECT status, COUNT(*) FROM tmp_kpi_window GROUP BY status

-- REPORT: daily_totals_source
SELECT day, source, COUNT(*) FROM tmp_kpi_window GROUP BY day, source;
"""


def test_splits_setup_and_reports():
    setup, reports = load_sql_sections(SAMPLE)
    assert "CREATE TEMP TABLE tmp_kpi_window" in setup
    assert set(reports) == {"status_summary", "daily_totals_source"}


def test_report_body_terminated_with_semicolon():
    _, reports = load_sql_sections(SAMPLE)
    assert reports["status_summary"].rstrip().endswith(";")


def test_no_reports_raises():
    with pytest.raises(SystemExit):
        load_sql_sections("-- SETUP: build_temp\nSELECT 1;\n")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python -m pytest tests/test_sql_sections.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_sql_sections'`.

- [ ] **Step 3: Replace `REPORT_HEADER` + `load_sql_reports` with a section parser**

In `Day2Day_Utillites/portfolio_kpi_metrics_postgres.py`, replace the line:

```python
REPORT_HEADER = re.compile(r"^--\s*REPORT:\s*(\w+)\s*$", re.MULTILINE)
```
with:
```python
SECTION_HEADER = re.compile(r"^--\s*(REPORT|SETUP):\s*(\w+)\s*$", re.MULTILINE)
```

Replace the entire `load_sql_reports` function with:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python -m pytest tests/test_sql_sections.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add Day2Day_Utillites/portfolio_kpi_metrics_postgres.py Day2Day_Utillites/tests/test_sql_sections.py
git commit -m "feat(kpi-metrics): parse SETUP + REPORT sections from SQL file"
```

---

### Task 5: Rewrite the SQL file (SETUP temp tables + all reports)

**Files:**
- Modify (full rewrite): `Day2Day_Utillites/Docs/portfolio-kpi-metrics.sql`
- Test: `Day2Day_Utillites/tests/test_sql_file.py`

**Interfaces:**
- Consumes: `load_sql_file_sections` (Task 4), `SQL_FILE` constant, `ALL_REPORT_KEYS`, `PIVOT_SPECS`, `REPORT_ALIASES` (Task 3).
- Produces: a SQL file whose SETUP builds `tmp_kpi_window` + `tmp_kpi_entity` and whose REPORT markers cover every SQL marker referenced by `REPORT_ALIASES.values()`.

- [ ] **Step 1: Write the failing test (real file must parse to the expected markers)**

Create `Day2Day_Utillites/tests/test_sql_file.py`:

```python
import pytest

import portfolio_kpi_metrics_postgres as mod


@pytest.fixture
def sections():
    return mod.load_sql_file_sections(mod.SQL_FILE)


def test_setup_builds_both_temp_tables(sections):
    setup_sql, _ = sections
    assert "CREATE TEMP TABLE tmp_kpi_window" in setup_sql
    assert "CREATE TEMP TABLE tmp_kpi_entity" in setup_sql
    assert "DROP TABLE IF EXISTS" in setup_sql


def test_every_alias_target_marker_exists(sections):
    _, reports = sections
    missing = set(mod.REPORT_ALIASES.values()) - set(reports)
    assert missing == set(), f"SQL file missing markers: {missing}"


def test_all_report_keys_present(sections):
    _, reports = sections
    assert set(mod.ALL_REPORT_KEYS) - set(reports) == set()


def test_pivot_markers_return_expected_value_column(sections):
    _, reports = sections
    for marker in mod.PIVOT_SPECS:
        assert marker in reports
        assert "refresh_count" in reports[marker]


def test_reports_read_temp_tables_not_base_table(sections):
    # Report bodies must not scan the base table directly.
    _, reports = sections
    for name, body in reports.items():
        assert "portfolio_kpi_update_log" not in body, f"{name} still references the base table"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python -m pytest tests/test_sql_file.py -v`
Expected: FAIL — current file has no SETUP block / new markers / still references base table.

- [ ] **Step 3: Rewrite the SQL file**

Overwrite `Day2Day_Utillites/Docs/portfolio-kpi-metrics.sql` with the following complete content:

````sql
-- Portfolio KPI update log — operational metrics (optimized: temp-table strategy)
-- Table: public.portfolio_kpi_update_log (partitioned on message_created_at)
--
-- Python runner (uses .env; sets the same session params + builds temp tables automatically):
--   python portfolio_kpi_metrics_postgres.py --start "2026-05-20 00:00:00" --end "2026-05-21 00:00:00" --report all
--
-- DBeaver: run PARAMS once, then run the SETUP block once, then run any REPORT.
-- Sections are tagged with:  -- SETUP: <name>   and   -- REPORT: <name>

-- =============================================================================
-- PARAMS — edit ONLY these three values, then Execute once per session.
-- =============================================================================
SELECT
  set_config('portfolio_kpi.window_start', '2026-05-20 00:00:00', false),
  set_config('portfolio_kpi.window_end',   '2026-05-21 00:00:00', false),
  set_config('portfolio_kpi.source_filter', '', false);
-- window_start  : inclusive lower bound (timestamp text)
-- window_end    : exclusive upper bound (timestamp text)
-- source_filter : '' = all sources; else e.g. 'Custom Financials' (scopes the WHOLE run)

-- =============================================================================
-- SETUP: build_temp
-- Materialize the windowed slice ONCE (source extracted to a plain column,
-- entity array pre-unnested), so every report below is a cheap temp-table scan.
-- Run this ONCE per session (after PARAMS). Re-running rebuilds the temp tables.
-- =============================================================================
DROP TABLE IF EXISTS tmp_kpi_entity;
DROP TABLE IF EXISTS tmp_kpi_window;

CREATE TEMP TABLE tmp_kpi_window AS
WITH params AS (
  SELECT
    current_setting('portfolio_kpi.window_start')::timestamp AS start_ts,
    current_setting('portfolio_kpi.window_end')::timestamp   AS end_ts,
    NULLIF(TRIM(current_setting('portfolio_kpi.source_filter')), '')::text AS source_filter
)
SELECT
  l.id,
  l.message_created_at,
  l.message_id,
  l.portfolio_id,
  COALESCE(l.status, '(null)')                             AS status,
  COALESCE(l.entity_refresh_message->>'source', '(null)')  AS source,
  l.entity_refresh_message->>'group'                       AS "group",
  date_trunc('day', l.message_created_at)::date            AS day,
  l.message_received_at,
  l.processing_started_at,
  l.processing_completed_at,
  l.duration_seconds,
  CASE
    WHEN l.processing_started_at IS NOT NULL
     AND l.processing_completed_at IS NOT NULL
     AND l.processing_completed_at >= l.processing_started_at
    THEN ROUND(EXTRACT(EPOCH FROM (l.processing_completed_at - l.processing_started_at))::numeric, 3)
  END AS process_seconds_computed,
  CASE
    WHEN l.processing_started_at IS NOT NULL
     AND l.message_received_at IS NOT NULL
    THEN ROUND(EXTRACT(EPOCH FROM (l.processing_started_at - l.message_received_at))::numeric, 3)
  END AS queue_wait_seconds,
  l.triggering_entity_external_ids,
  l.entity_refresh_message
FROM public.portfolio_kpi_update_log l
CROSS JOIN params p
WHERE l.message_created_at >= p.start_ts
  AND l.message_created_at <  p.end_ts
  AND (p.source_filter IS NULL OR l.entity_refresh_message->>'source' = p.source_filter);

CREATE INDEX ON tmp_kpi_window (source);
CREATE INDEX ON tmp_kpi_window (day);
CREATE INDEX ON tmp_kpi_window (status);
ANALYZE tmp_kpi_window;

CREATE TEMP TABLE tmp_kpi_entity AS
SELECT
  w.day,
  w.portfolio_id,
  w.source,
  w.status,
  entity_id
FROM tmp_kpi_window w
CROSS JOIN LATERAL unnest(w.triggering_entity_external_ids) AS entity_id
WHERE w.triggering_entity_external_ids IS NOT NULL
  AND cardinality(w.triggering_entity_external_ids) > 0;

CREATE INDEX ON tmp_kpi_entity (source);
CREATE INDEX ON tmp_kpi_entity (day);
CREATE INDEX ON tmp_kpi_entity (entity_id);
CREATE INDEX ON tmp_kpi_entity (portfolio_id);
ANALYZE tmp_kpi_entity;

-- =============================================================================
-- REPORT: daily_totals_source
-- Message counts per day, broken down by source.
-- =============================================================================
SELECT
  day,
  source,
  COUNT(*) AS message_count
FROM tmp_kpi_window
GROUP BY day, source
ORDER BY day, source;

-- =============================================================================
-- REPORT: hourly_totals
-- Messages received per hour vs processed per hour, broken down by source.
-- =============================================================================
WITH received AS (
  SELECT date_trunc('hour', message_received_at) AS hour_utc, source,
         COUNT(*) AS messages_received
  FROM tmp_kpi_window
  WHERE message_received_at IS NOT NULL
    AND message_received_at >= current_setting('portfolio_kpi.window_start')::timestamp
    AND message_received_at <  current_setting('portfolio_kpi.window_end')::timestamp
  GROUP BY 1, 2
),
processed AS (
  SELECT date_trunc('hour', processing_completed_at) AS hour_utc, source,
         COUNT(*) AS messages_processed
  FROM tmp_kpi_window
  WHERE processing_completed_at IS NOT NULL
    AND processing_completed_at >= current_setting('portfolio_kpi.window_start')::timestamp
    AND processing_completed_at <  current_setting('portfolio_kpi.window_end')::timestamp
  GROUP BY 1, 2
)
SELECT
  COALESCE(r.hour_utc, p.hour_utc) AS hour_utc,
  COALESCE(r.source, p.source)     AS source,
  COALESCE(r.messages_received, 0)  AS messages_received,
  COALESCE(p.messages_processed, 0) AS messages_processed
FROM received r
FULL OUTER JOIN processed p ON p.hour_utc = r.hour_utc AND p.source = r.source
ORDER BY hour_utc, source;

-- =============================================================================
-- REPORT: hourly_by_status
-- Messages received vs processed per hour, broken down by status.
-- =============================================================================
WITH received AS (
  SELECT date_trunc('hour', message_received_at) AS hour_utc, status,
         COUNT(*) AS messages_received
  FROM tmp_kpi_window
  WHERE message_received_at IS NOT NULL
    AND message_received_at >= current_setting('portfolio_kpi.window_start')::timestamp
    AND message_received_at <  current_setting('portfolio_kpi.window_end')::timestamp
  GROUP BY 1, 2
),
processed AS (
  SELECT date_trunc('hour', processing_completed_at) AS hour_utc, status,
         COUNT(*) AS messages_processed
  FROM tmp_kpi_window
  WHERE processing_completed_at IS NOT NULL
    AND processing_completed_at >= current_setting('portfolio_kpi.window_start')::timestamp
    AND processing_completed_at <  current_setting('portfolio_kpi.window_end')::timestamp
  GROUP BY 1, 2
)
SELECT
  COALESCE(r.hour_utc, p.hour_utc) AS hour_utc,
  COALESCE(r.status, p.status)     AS status,
  COALESCE(r.messages_received, 0)  AS messages_received,
  COALESCE(p.messages_processed, 0) AS messages_processed
FROM received r
FULL OUTER JOIN processed p ON p.hour_utc = r.hour_utc AND p.status = r.status
ORDER BY hour_utc, status;

-- =============================================================================
-- REPORT: status_summary
-- Row counts by status in the window.
-- =============================================================================
SELECT
  status,
  COUNT(*) AS row_count
FROM tmp_kpi_window
GROUP BY status
ORDER BY row_count DESC;

-- =============================================================================
-- REPORT: source_update_totals
-- Total updates and distinct portfolios per source.
-- =============================================================================
SELECT
  source,
  COUNT(*) AS total_updates,
  COUNT(DISTINCT portfolio_id) AS portfolios_updated,
  MIN(message_created_at) AS first_update_at,
  MAX(message_created_at) AS last_update_at
FROM tmp_kpi_window
GROUP BY source
ORDER BY total_updates DESC, source;

-- =============================================================================
-- REPORT: portfolio_updates_by_source
-- Update count per portfolio, broken down by source.
-- =============================================================================
SELECT
  portfolio_id,
  source,
  COUNT(*) AS update_count,
  MIN(message_created_at) AS first_update_at,
  MAX(message_created_at) AS last_update_at
FROM tmp_kpi_window
GROUP BY portfolio_id, source
ORDER BY portfolio_id, source;

-- =============================================================================
-- REPORT: portfolio_update_totals
-- Total update count per portfolio (all sources).
-- =============================================================================
SELECT
  portfolio_id,
  COUNT(*) AS update_count
FROM tmp_kpi_window
GROUP BY portfolio_id
ORDER BY update_count DESC, portfolio_id;

-- =============================================================================
-- REPORT: entity_source_totals
-- Entity triggers per source (array unnested): totals only.
-- =============================================================================
SELECT
  source,
  COUNT(*) AS entity_trigger_count,
  COUNT(DISTINCT entity_id) AS distinct_entities,
  COUNT(DISTINCT portfolio_id) AS portfolios_affected
FROM tmp_kpi_entity
GROUP BY source
ORDER BY entity_trigger_count DESC, source;

-- =============================================================================
-- REPORT: triggering_entity_counts
-- Per-entity trigger counts, broken down by source.
-- =============================================================================
SELECT
  entity_id,
  source,
  COUNT(*) AS trigger_count,
  COUNT(DISTINCT portfolio_id) AS portfolios_affected
FROM tmp_kpi_entity
GROUP BY entity_id, source
ORDER BY trigger_count DESC, entity_id, source;

-- =============================================================================
-- REPORT: triggering_entity_counts_by_day
-- Entity triggers per day, broken down by source.
-- =============================================================================
SELECT
  day,
  source,
  COUNT(*) AS entity_trigger_count,
  COUNT(DISTINCT entity_id) AS distinct_entities,
  COUNT(DISTINCT portfolio_id) AS portfolios_affected
FROM tmp_kpi_entity
GROUP BY day, source
ORDER BY day, source;

-- =============================================================================
-- REPORT: entities_by_day_source_status   (#1)
-- Entity triggers per day, per source, per status.
-- =============================================================================
SELECT
  day,
  source,
  status,
  COUNT(*) AS entity_trigger_count,
  COUNT(DISTINCT entity_id) AS distinct_entities,
  COUNT(DISTINCT portfolio_id) AS portfolios_affected
FROM tmp_kpi_entity
GROUP BY day, source, status
ORDER BY day, source, status;

-- =============================================================================
-- REPORT: portfolios_by_day_source_status   (#2)
-- Portfolio refreshes (messages) per day, per source, per status.
-- =============================================================================
SELECT
  day,
  source,
  status,
  COUNT(*) AS message_count,
  COUNT(DISTINCT portfolio_id) AS distinct_portfolios
FROM tmp_kpi_window
GROUP BY day, source, status
ORDER BY day, source, status;

-- =============================================================================
-- REPORT: entity_by_source   (#3a, pivoted to 2D in Python)
-- Long form: how many times each entity was refreshed, per source.
-- =============================================================================
SELECT
  entity_id,
  source,
  COUNT(*) AS refresh_count
FROM tmp_kpi_entity
GROUP BY entity_id, source
ORDER BY entity_id, source;

-- =============================================================================
-- REPORT: portfolio_entity_source   (#3b, pivoted to 2D in Python)
-- Long form: how many times each (portfolio, entity) pair was refreshed, per source.
-- =============================================================================
SELECT
  portfolio_id,
  entity_id,
  source,
  COUNT(*) AS refresh_count
FROM tmp_kpi_entity
GROUP BY portfolio_id, entity_id, source
ORDER BY portfolio_id, entity_id, source;

-- =============================================================================
-- REPORT: slow_global
-- Completed messages slower than global P95 processing time in the window.
-- =============================================================================
WITH completed AS (
  SELECT
    id, message_created_at, message_id, portfolio_id, status, source, "group",
    entity_refresh_message, triggering_entity_external_ids,
    message_received_at, processing_started_at, processing_completed_at,
    process_seconds_computed,
    duration_seconds AS process_seconds_stored,
    queue_wait_seconds
  FROM tmp_kpi_window
  WHERE process_seconds_computed IS NOT NULL
),
baseline AS (
  SELECT
    COUNT(*) AS sample_size,
    ROUND(AVG(process_seconds_computed)::numeric, 3) AS avg_process_sec,
    ROUND((PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY process_seconds_computed))::numeric, 3) AS median_process_sec,
    ROUND((PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY process_seconds_computed))::numeric, 3) AS p95_process_sec,
    ROUND((PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY process_seconds_computed))::numeric, 3) AS p99_process_sec
  FROM completed
)
SELECT
  c.id, c.message_created_at, c.message_id, c.portfolio_id, c.status, c.source, c."group",
  c.entity_refresh_message, c.triggering_entity_external_ids,
  c.message_received_at, c.processing_started_at, c.processing_completed_at,
  c.process_seconds_computed, c.process_seconds_stored, c.queue_wait_seconds,
  b.sample_size, b.avg_process_sec, b.median_process_sec, b.p95_process_sec, b.p99_process_sec,
  ROUND((c.process_seconds_computed / NULLIF(b.median_process_sec, 0))::numeric, 2) AS times_median,
  ROUND((c.process_seconds_computed / NULLIF(b.p95_process_sec, 0))::numeric, 2) AS times_p95
FROM completed c
CROSS JOIN baseline b
WHERE c.process_seconds_computed > b.p95_process_sec
ORDER BY c.process_seconds_computed DESC;

-- =============================================================================
-- REPORT: slow_by_source
-- Slow = above P95 processing time within each source.
-- =============================================================================
WITH completed AS (
  SELECT
    id, message_created_at, message_id, portfolio_id, status, source, "group",
    entity_refresh_message, triggering_entity_external_ids,
    message_received_at, processing_started_at, processing_completed_at,
    process_seconds_computed,
    duration_seconds AS process_seconds_stored
  FROM tmp_kpi_window
  WHERE process_seconds_computed IS NOT NULL
),
baseline_by_source AS (
  SELECT
    source,
    COUNT(*) AS sample_size,
    ROUND((PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY process_seconds_computed))::numeric, 3) AS p95_process_sec
  FROM completed
  GROUP BY source
)
SELECT
  c.id, c.message_created_at, c.message_id, c.portfolio_id, c.status, c.source, c."group",
  c.entity_refresh_message, c.triggering_entity_external_ids,
  c.message_received_at, c.processing_started_at, c.processing_completed_at,
  c.process_seconds_computed, c.process_seconds_stored,
  b.sample_size, b.p95_process_sec,
  ROUND((c.process_seconds_computed / NULLIF(b.p95_process_sec, 0))::numeric, 2) AS times_source_p95
FROM completed c
JOIN baseline_by_source b ON b.source = c.source
WHERE c.process_seconds_computed > b.p95_process_sec
ORDER BY c.process_seconds_computed DESC;
````

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python -m pytest tests/test_sql_file.py -v`
Expected: PASS (5 tests). If `test_every_alias_target_marker_exists` fails, the failure message names the missing marker — add it to the SQL file.

- [ ] **Step 5: Commit**

```bash
git add Day2Day_Utillites/Docs/portfolio-kpi-metrics.sql Day2Day_Utillites/tests/test_sql_file.py
git commit -m "perf(kpi-metrics): temp-table SETUP + reports read tmp tables; add new reports"
```

---

### Task 6: Runner wiring (execute SETUP, pivots, `--env`, `--top`)

**Files:**
- Modify: `Day2Day_Utillites/portfolio_kpi_metrics_postgres.py`
- Test: `Day2Day_Utillites/tests/test_report_routing.py`

**Interfaces:**
- Consumes: `load_sql_file_sections`, `pivot_rows`, `PIVOT_SPECS`, `resolve_reports`, `load_env`, `PostgresSettings`.
- Produces: `is_pivot(report_key: str) -> bool`; updated `run_reports(settings, window_start, window_end, report_keys, source, export_csv, top)` that executes `setup_sql` once then runs each report (pivoting when `report_key in PIVOT_SPECS`); `main()` with `--env` and `--top`.

- [ ] **Step 1: Write the failing test**

Create `Day2Day_Utillites/tests/test_report_routing.py`:

```python
import argparse

import portfolio_kpi_metrics_postgres as mod


def test_is_pivot():
    assert mod.is_pivot("entity_by_source")
    assert mod.is_pivot("portfolio_entity_source")
    assert not mod.is_pivot("status_summary")


def test_parser_accepts_env_and_top():
    # ensure --env and --top are wired without running a query.
    p = mod.build_arg_parser()
    assert isinstance(p, argparse.ArgumentParser)
    ns = p.parse_args([
        "--start", "2026-05-20 00:00:00",
        "--end", "2026-05-21 00:00:00",
        "--report", "entity_by_source",
        "--env", "qa",
        "--top", "25",
    ])
    assert ns.env == "qa"
    assert ns.top == 25
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python -m pytest tests/test_report_routing.py -v`
Expected: FAIL — `is_pivot` / `build_arg_parser` not defined.

- [ ] **Step 3: Add `is_pivot`, refactor the parser into `build_arg_parser`, wire SETUP + pivots + `--env`/`--top`**

In `Day2Day_Utillites/portfolio_kpi_metrics_postgres.py`:

(a) Add near `resolve_reports`:

```python
def is_pivot(report_key: str) -> bool:
    return report_key in PIVOT_SPECS
```

(b) Replace the body of `run_reports` with the version below (note the new `top` parameter and the SETUP/pivot handling; it uses `load_sql_file_sections` from Task 4):

```python
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

            if is_pivot(report_key):
                index_cols, pivot_col, value_col = PIVOT_SPECS[report_key]
                dict_rows = pivot_rows(dict_rows, index_cols, pivot_col, value_col, top=top)

            title = f"{report_key}  |  window [{window_start}] .. [{window_end})"
            if source:
                title += f"  |  source={source!r}"
            if is_pivot(report_key) and top is not None:
                title += f"  |  top={top}"
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
```

(c) Extract the argument parser into `build_arg_parser` and add `--env` / `--top`. Replace the argparse construction inside `main()` with a call to this new function. Add:

```python
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
```

(d) Rewrite `main()` to parse first, then load env, then run (note `import os` is already present via `run_portfolio_kpis_postgres`? No — add `import os` to this file's imports if absent):

```python
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
```

Ensure `import os` is in the import block at the top of the file (add it if missing).

Note: Task 1 leaves `main()` calling `load_env(None)`; this step replaces that whole `main()` body, so the temporary call is superseded here.

- [ ] **Step 4: Run the routing test + this plan's suite + `--help` smoke**

Run: `.\.venv\Scripts\python -m pytest tests/test_env_loading.py tests/test_pivot_rows.py tests/test_report_registry.py tests/test_sql_sections.py tests/test_sql_file.py tests/test_report_routing.py -v`
Expected: PASS (all tests across this plan's 6 test modules).

Run: `.\.venv\Scripts\python portfolio_kpi_metrics_postgres.py --help`
Expected: exit 0; help shows `--env`, `--top`, and the expanded `--report` choices.

- [ ] **Step 5: Commit**

```bash
git add Day2Day_Utillites/portfolio_kpi_metrics_postgres.py Day2Day_Utillites/tests/test_report_routing.py
git commit -m "feat(kpi-metrics): execute SETUP once, pivot dispatch, --env/--top wiring"
```

- [ ] **Step 6: Deferred manual DB verification (run once non-prod creds exist)**

This cannot run now (no non-prod credentials). Record it for the operator; run from `Day2Day_Utillites`:

```
copy .env.qa.example .env.qa   # then fill TESSERA_POSTGRES_* for QA
.\.venv\Scripts\python portfolio_kpi_metrics_postgres.py --env qa ^
  --start "2026-06-05 00:00:00" --end "2026-06-30 23:59:00" --report all
.\.venv\Scripts\python portfolio_kpi_metrics_postgres.py --env qa ^
  --start "2026-06-05 00:00:00" --end "2026-06-30 23:59:00" --report entity_by_source --top 50
```
Expected: each report prints a table; counts are non-negative; the second prints a pivot with a `total` column capped at 50 rows. Parity check: `entities_by_day` totals equal the operator's original `triggering_entity_counts_by_day` query for the same window.

---

### Task 7: Per-env `.env` templates + gitignore

**Files:**
- Create: `Day2Day_Utillites/.env.ci.example`, `Day2Day_Utillites/.env.qa.example`, `Day2Day_Utillites/.env.stg.example`
- Modify: `Day2Day_Utillites/.gitignore`

**Interfaces:** none (config files).

- [ ] **Step 1: Update `.gitignore`**

In `Day2Day_Utillites/.gitignore`, replace the top block:

```
# Local secrets (copy from .env.example and fill in)
.env
```
with:
```
# Local secrets — base and per-env files are ignored; only *.example templates are tracked.
.env
.env.*
!.env.example
!*.example
```

- [ ] **Step 2: Create the three templates**

Create `Day2Day_Utillites/.env.ci.example`:

```
# Day2Day Utilities — CI environment (read-only KPI reports).
# Copy to ".env.ci" and fill in real values. ".env.ci" is gitignored.
# Selected at runtime with:  python portfolio_kpi_metrics_postgres.py --env ci ...

# --- Tessera Postgres (CI) ---
TESSERA_POSTGRES_HOST=
TESSERA_POSTGRES_PORT=5432
TESSERA_POSTGRES_DB=
TESSERA_POSTGRES_USER=
TESSERA_POSTGRES_PASSWORD=
```

Create `Day2Day_Utillites/.env.qa.example` (identical but "QA" / `--env qa`):

```
# Day2Day Utilities — QA environment (read-only KPI reports).
# Copy to ".env.qa" and fill in real values. ".env.qa" is gitignored.
# Selected at runtime with:  python portfolio_kpi_metrics_postgres.py --env qa ...

# --- Tessera Postgres (QA) ---
TESSERA_POSTGRES_HOST=
TESSERA_POSTGRES_PORT=5432
TESSERA_POSTGRES_DB=
TESSERA_POSTGRES_USER=
TESSERA_POSTGRES_PASSWORD=
```

Create `Day2Day_Utillites/.env.stg.example` (identical but "STG" / `--env stg`):

```
# Day2Day Utilities — STG environment (read-only KPI reports).
# Copy to ".env.stg" and fill in real values. ".env.stg" is gitignored.
# Selected at runtime with:  python portfolio_kpi_metrics_postgres.py --env stg ...

# --- Tessera Postgres (STG) ---
TESSERA_POSTGRES_HOST=
TESSERA_POSTGRES_PORT=5432
TESSERA_POSTGRES_DB=
TESSERA_POSTGRES_USER=
TESSERA_POSTGRES_PASSWORD=
```

- [ ] **Step 3: Verify ignore rules (filled-in files ignored; templates tracked)**

Run:
```bash
printf 'TESSERA_POSTGRES_HOST=x\n' > Day2Day_Utillites/.env.qa
git check-ignore Day2Day_Utillites/.env.qa && echo "IGNORED-OK"
git check-ignore Day2Day_Utillites/.env.qa.example || echo "TEMPLATE-TRACKED-OK"
rm Day2Day_Utillites/.env.qa
```
Expected: prints `Day2Day_Utillites/.env.qa` then `IGNORED-OK`, then `TEMPLATE-TRACKED-OK` (the `.example` is NOT ignored).

- [ ] **Step 4: Commit**

```bash
git add Day2Day_Utillites/.gitignore Day2Day_Utillites/.env.ci.example Day2Day_Utillites/.env.qa.example Day2Day_Utillites/.env.stg.example
git commit -m "chore(day2day): per-env .env templates + gitignore for .env.<env>"
```

---

### Task 8: Docs, optional index migration, catalog entry

**Files:**
- Modify: `Day2Day_Utillites/Docs/portfolio-kpi-metrics.md`
- Create: `Day2Day_Utillites/Docs/portfolio-kpi-indexes.sql`
- Modify: `Day2Day_Utillites/utilities.yaml` (the `portfolio-kpi-metrics-postgres` entry)

**Interfaces:** none (docs/config).

- [ ] **Step 1: Create the optional prod-index migration**

Create `Day2Day_Utillites/Docs/portfolio-kpi-indexes.sql`:

```sql
-- OPTIONAL performance aid for ad-hoc DBeaver queries that hit the BASE table
-- directly (public.portfolio_kpi_update_log). The Python runner does NOT need
-- this — it materializes temp tables. Run in a maintenance window.
--
-- Speeds up filtering/grouping by source, which today requires a JSONB
-- extraction on every row (the existing GIN index only helps containment @>).

-- Option A — per partition, non-blocking (repeat for each partition):
--   CREATE INDEX CONCURRENTLY IF NOT EXISTS
--     idx_<partition>_source
--     ON public.<partition_name> ((entity_refresh_message->>'source'));

-- Option B — on the partitioned parent (cascades to partitions, but takes a
-- brief lock and CANNOT be combined with CONCURRENTLY on the parent):
CREATE INDEX IF NOT EXISTS idx_portfolio_kpi_log_source
  ON public.portfolio_kpi_update_log ((entity_refresh_message->>'source'));

-- Verify:
--   SELECT indexname FROM pg_indexes
--   WHERE tablename = 'portfolio_kpi_update_log' AND indexname LIKE '%source%';
```

- [ ] **Step 2: Update the runner doc**

In `Day2Day_Utillites/Docs/portfolio-kpi-metrics.md`, update the Reports table and options to cover the new reports and flags. Replace the "### Reports" table with:

```markdown
### Reports

| `--report` | What it measures |
|------------|------------------|
| `daily` | Message counts per day, per source |
| `hourly` | Received vs processed per hour, per source |
| `hourly_by_status` | Received vs processed per hour, per status |
| `status` | Row counts by status |
| `source_update_totals` | Total updates + distinct portfolios per source |
| `portfolio_updates_by_source` | Update count per portfolio, per source |
| `portfolio_update_totals` | Total update count per portfolio |
| `entity_counts` | Per-entity trigger counts, per source |
| `entity_source_totals` | Entity trigger totals per source |
| `entities_by_day` | Entity triggers per day, per source |
| `entities_by_day_source_status` | Entity triggers per day / source / status (#1) |
| `portfolios_by_day_source_status` | Portfolio refreshes per day / source / status (#2) |
| `entity_by_source` | 2D pivot: entity × source (#3a) |
| `portfolio_entity_source` | 2D pivot: (portfolio, entity) × source (#3b) |
| `slow` | Completed jobs slower than global P95 |
| `slow_by_source` | Slow relative to per-source P95 |
| `all` | Runs the aggregate reports (not slow detail / pivots) |

Flags: `--source NAME` scopes the whole run; `--top N` caps stdout rows for the
two pivot reports; `--env {ci,qa,stg,prod}` loads `.env.<env>` ahead of base `.env`;
`--export-csv PATH` writes one CSV per report (relative → `output/portfolio_kpi_metrics/`).

### Performance

The runner builds two session TEMP tables once per run (`tmp_kpi_window`,
`tmp_kpi_entity`) with `source` extracted to a plain column and the entity array
pre-`unnest`ed, then every report reads from them — one base-table scan instead
of one per report. For ad-hoc base-table queries in DBeaver, see the optional
`portfolio-kpi-indexes.sql`.
```

Also update the DBeaver section to add a build step after PARAMS:

```markdown
### Step 1b — Build the working set (SETUP, once per session)

After PARAMS, select the `-- SETUP: build_temp` block and Execute it once.
It creates `tmp_kpi_window` and `tmp_kpi_entity`. Every REPORT reads from these,
so re-run SETUP whenever you change the PARAMS window/source.
```

- [ ] **Step 3: Update the catalog entry**

In `Day2Day_Utillites/utilities.yaml`, update the `portfolio-kpi-metrics-postgres` entry's `args` and `purpose` to include the new reports and flags. Replace its `args` list with:

```yaml
    args:
      - flag: --start
        required: true
        help: 'Window start inclusive, e.g. "2026-05-20 00:00:00".'
      - flag: --end
        required: true
        help: 'Window end exclusive, e.g. "2026-05-21 00:00:00".'
      - flag: --report
        required: true
        choices: [daily, hourly, hourly_by_status, status, source_update_totals, portfolio_updates_by_source, portfolio_update_totals, entity_counts, entity_source_totals, entities_by_day, entities_by_day_source_status, portfolios_by_day_source_status, entity_by_source, portfolio_entity_source, slow, slow_by_source, all]
        help: "Which report to run."
      - flag: --source
        help: 'Scope the whole run to a source (e.g. "Custom Financials").'
      - flag: --env
        help: "Load .env.<env> ahead of base .env (ci, qa, stg, prod)."
      - flag: --top
        type: int
        help: "Cap stdout rows for pivot reports (entity_by_source, portfolio_entity_source)."
      - flag: --export-csv
        help: "Write each report to CSV (relative → output/portfolio_kpi_metrics/)."
```

And update its `purpose`:

```yaml
    purpose: "Optimized reports on portfolio_kpi_update_log via session temp tables: daily/hourly/status volume, per-source/entity/portfolio counts, day/source/status breakdowns, 2D pivots, and slow-message analysis. Multi-env via --env."
```

- [ ] **Step 4: Verify docs/config parse**

Run:
```bash
.\.venv\Scripts\python -c "import yaml; yaml.safe_load(open('utilities.yaml', encoding='utf-8')); print('yaml ok')"
```
Expected: `yaml ok`.

- [ ] **Step 5: Commit**

```bash
git add Day2Day_Utillites/Docs/portfolio-kpi-metrics.md Day2Day_Utillites/Docs/portfolio-kpi-indexes.sql Day2Day_Utillites/utilities.yaml
git commit -m "docs(kpi-metrics): document new reports, --env/--top, temp-table perf, optional index"
```

---

## Final verification

- [ ] Run this plan's suite once more: `.\.venv\Scripts\python -m pytest tests/test_env_loading.py tests/test_pivot_rows.py tests/test_report_registry.py tests/test_sql_sections.py tests/test_sql_file.py tests/test_report_routing.py -v` — all green. (Optionally `python -m pytest tests/ -v` to confirm no regressions in the existing suite.)
- [ ] `.\.venv\Scripts\python portfolio_kpi_metrics_postgres.py --help` exits 0 and lists new flags/reports.
- [ ] `git status` clean; no `.env`, `.env.ci/.qa/.stg` (non-example) tracked.
- [ ] Deferred (operator, with non-prod creds): Task 6 Step 6 manual DB smoke + parity check.
