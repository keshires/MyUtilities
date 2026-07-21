from datetime import date
import pd_precheck as p

REF = date(2026, 7, 1)


def test_post_ids_keeps_only_post_actions():
    rows = [
        p.StaleRow("keep1", "t1", date(2026, 5, 1), None, False),   # standalone POST
        p.StaleRow("skip1", "t1", date(2026, 6, 1), "B", True),     # matches stale group SKIP
        p.StaleRow("keep2", "t1", date(2026, 5, 1), "A", True),     # peer_lag POST
    ]
    resolver = p.DbMaxPeerGroupPdResolver(
        lambda ids: [("A", date(2026, 7, 1)), ("B", date(2026, 6, 1))]
    )
    ids = p.post_ids(rows, resolver, "custom", REF)
    assert ids == {"keep1", "keep2"}
