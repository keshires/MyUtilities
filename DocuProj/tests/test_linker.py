from engine.linker import DeterministicResolver, LinkQuery, url_path
from engine.models import CodeRef, Endpoint


def _ref():
    return CodeRef(repo="r", file="f", line=1, snippet="s")


def _endpoint(path):
    return Endpoint(id=f"edfx-api:GET:{path}", repo="edfx-api", method="GET", path=path,
                    handler_ref=_ref(), language="python")


def test_url_path_absolute_and_relative():
    assert url_path("https://ci-api.edfx.moodysanalytics.net/edfx/v2") == "/edfx/v2"
    assert url_path("/1.0") == "/1.0"
    assert url_path("") == ""


def _query(source_path, endpoint):
    return LinkQuery(source_label="edfxApiV2Url", source_path=source_path, source_ref=_ref(), endpoint=endpoint)


def test_resolver_exact_match_is_full_confidence():
    r = DeterministicResolver()
    assert r.score(_query("/edfx/v2", _endpoint("/edfx/v2"))) == 1.0


def test_resolver_prefix_match_is_partial_confidence():
    r = DeterministicResolver()
    assert r.score(_query("/edfx/v2", _endpoint("/edfx/v2/tools/customPd"))) == 0.5


def test_resolver_no_match_returns_none():
    r = DeterministicResolver()
    assert r.score(_query("/edfx/v2", _endpoint("/other/y"))) is None


def test_resolver_ignores_root_or_empty_source():
    r = DeterministicResolver()
    assert r.score(_query("/", _endpoint("/edfx/v2/x"))) is None
    assert r.score(_query("", _endpoint("/edfx/v2/x"))) is None
