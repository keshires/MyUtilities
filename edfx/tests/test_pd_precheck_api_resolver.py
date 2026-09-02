from datetime import date
import pd_precheck as p


def test_api_resolver_custom_composite_maps_back_to_external_id():
    def post_batch(ids):
        # server echoes the composite entityId it was given
        return [{"entityId": ids[0], "asOfDate": "2026-07-01", "pd": 0.01}]

    rows = [p.StaleRow("E1", "t", None, None, True, custom_id="c", financials_process_id="uuid1")]
    out = p.ApiEntityPdResolver(post_batch, batch_size=10).resolve(rows, "custom")
    assert set(out) == {"E1"}          # composite "E1-uuid1" mapped back to external_id
    assert out["E1"].has_pd is True


def test_api_resolver_batches_and_handles_no_data():
    seen = []

    def post_batch(ids):
        seen.append(len(ids))
        return [{"entityId": i, "message": "No data found"} for i in ids]

    rows = [p.StaleRow(f"E{i}", "t", None, None, False) for i in range(5)]
    out = p.ApiEntityPdResolver(post_batch, batch_size=2).resolve(rows, "private")
    assert seen == [2, 2, 1]           # batched by 2
    assert len(out) == 5 and all(v.has_pd is False for v in out.values())


def test_api_resolver_skips_custom_without_procid():
    def post_batch(ids):
        return [{"entityId": i, "asOfDate": "2026-07-01", "pd": 0.01} for i in ids]

    rows = [p.StaleRow("E1", "t", None, None, True, custom_id="c")]  # no financials_process_id
    out = p.ApiEntityPdResolver(post_batch, batch_size=10).resolve(rows, "custom")
    assert out == {}                   # cannot build composite -> not queried
