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
