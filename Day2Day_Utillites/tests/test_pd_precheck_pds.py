from datetime import date
import pd_precheck as p

REF = date(2026, 7, 1)


def test_pds_entity_id_private_is_external_id():
    r = p.StaleRow("EXT1", "t1", None, None, False)
    assert p.pds_entity_id(r, "private") == "EXT1"


def test_pds_entity_id_custom_is_composite():
    r = p.StaleRow("EXT1", "t1", None, None, True, custom_id="411",
                   financials_process_id="uuid-abc")
    assert p.pds_entity_id(r, "custom") == "EXT1-uuid-abc"


def test_pds_entity_id_custom_missing_procid_none():
    r = p.StaleRow("EXT1", "t1", None, None, True, custom_id="411")
    assert p.pds_entity_id(r, "custom") is None


def test_parse_pds_entity_has_pd():
    res = p.parse_pds_entity({"entityId": "X", "asOfDate": "2026-07-01", "pd": 0.0022})
    assert res.as_of_date == date(2026, 7, 1) and res.has_pd is True


def test_parse_pds_entity_bankrupt_no_pd():
    res = p.parse_pds_entity({"entityId": "X", "asOfDate": "2026-07-01", "confidence": "BKRPT"})
    assert res.as_of_date == date(2026, 7, 1) and res.has_pd is False


def test_parse_pds_entity_no_data_message():
    res = p.parse_pds_entity({"entityId": "X", "message": "No data found"})
    assert res.as_of_date is None and res.has_pd is False and res.message == "No data found"


def test_classify_by_pds_current_pd_posts():
    res = p.PdResult(date(2026, 7, 1), True)
    c = p.classify_by_pds("private", res, REF)
    assert (c.category, c.action) == ("current_pd", "POST")


def test_classify_by_pds_no_pd_skips():
    c = p.classify_by_pds("private", p.PdResult(date(2026, 7, 1), False, "Entity is bankrupt."), REF)
    assert (c.category, c.action) == ("no_pd", "SKIP")


def test_classify_by_pds_source_stale_skips():
    c = p.classify_by_pds("private", p.PdResult(date(2019, 12, 1), True), REF)
    assert (c.category, c.action) == ("source_stale", "SKIP")


def test_classify_by_pds_unknown_posts():
    c = p.classify_by_pds("private", None, REF)
    assert (c.category, c.action) == ("pds_unknown", "POST")


def test_post_ids_pds_with_static_resolver():
    rows = [
        p.StaleRow("A", "t1", None, None, False),  # current -> POST
        p.StaleRow("B", "t1", None, None, False),  # no_pd -> SKIP
        p.StaleRow("C", "t1", None, None, False),  # source_stale -> SKIP
    ]
    resolver = p.StaticEntityPdResolver({
        "A": p.PdResult(date(2026, 7, 1), True),
        "B": p.PdResult(date(2026, 7, 1), False, "bankrupt"),
        "C": p.PdResult(date(2019, 1, 1), True),
    })
    assert p.post_ids_pds(rows, resolver, "private", REF) == {"A"}
