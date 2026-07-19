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
