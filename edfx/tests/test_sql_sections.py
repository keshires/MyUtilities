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
