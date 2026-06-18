from engine.cache import cache_key
from engine.models import Project, RepoRef


def _project(sha_a="aaa", sha_b="bbb"):
    return Project(
        id="edfx-flow",
        name="EDFX Flow",
        repos=[
            RepoRef(url="https://x/edfx-api", folder="edfx-api", branch="main", sha=sha_a),
            RepoRef(url="https://x/edfx-ui", folder="edfx-app-ui", branch="main", sha=sha_b),
        ],
    )


def test_cache_key_is_stable():
    assert cache_key(_project()) == cache_key(_project())


def test_cache_key_independent_of_repo_order():
    p1 = _project()
    p2 = Project(id="edfx-flow", name="EDFX Flow", repos=list(reversed(p1.repos)))
    assert cache_key(p1) == cache_key(p2)


def test_cache_key_changes_with_sha():
    assert cache_key(_project()) != cache_key(_project(sha_a="zzz"))


from engine.cache import Cache
from engine.models import AnalysisModel


def _model():
    return AnalysisModel(project=_project(), endpoints=[], flows=[])


def test_cache_miss_returns_none(tmp_path):
    cache = Cache(tmp_path)
    assert cache.get("does-not-exist") is None


def test_cache_put_then_get_round_trips(tmp_path):
    cache = Cache(tmp_path)
    model = _model()
    key = cache_key(model.project)
    cache.put(key, model)
    assert cache.get(key) == model


def test_cache_writes_camelcase_json(tmp_path):
    cache = Cache(tmp_path)
    model = _model()
    key = cache_key(model.project)
    cache.put(key, model)
    text = (tmp_path / f"{key}.json").read_text(encoding="utf-8")
    assert '"project"' in text
