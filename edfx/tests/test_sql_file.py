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
