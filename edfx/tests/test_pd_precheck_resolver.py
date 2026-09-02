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
        p.StaleRow("e1", "t1", date(2026, 5, 1), "A", True),    # lags fresh group -> POST
        p.StaleRow("e2", "t1", date(2026, 5, 1), None, False),  # standalone -> POST
        p.StaleRow("e3", "t1", date(2026, 6, 1), "B", True),    # matches stale group -> SKIP
    ]
    resolver = p.DbMaxPeerGroupPdResolver(
        lambda ids: [("A", date(2026, 7, 1)), ("B", date(2026, 6, 1))]
    )
    out = p.classify_all(rows, resolver, "custom", REF)
    actions = {r.external_id: c.action for r, c in out}
    assert actions == {"e1": "POST", "e2": "POST", "e3": "SKIP"}
