import pd_precheck as p


def test_financials_completed():
    assert p.financials_completed("Completed") is True
    assert p.financials_completed("Completed with errors") is False
    assert p.financials_completed("Failed") is False
    assert p.financials_completed("") is False
    assert p.financials_completed(None) is False
    assert p.financials_completed("  Completed  ") is True  # trimmed
