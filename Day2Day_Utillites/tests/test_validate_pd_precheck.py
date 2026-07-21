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
