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
