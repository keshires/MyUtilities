from engine.analyze import detect_language


def test_detect_angular(tmp_path):
    (tmp_path / "angular.json").write_text("{}", encoding="utf-8")
    assert detect_language(tmp_path) == "angular"


def test_detect_python(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    assert detect_language(tmp_path) == "python"


def test_detect_typescript(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert detect_language(tmp_path) == "typescript"


def test_detect_unknown(tmp_path):
    assert detect_language(tmp_path) is None


from pathlib import Path

from engine.analyze import analyze
from engine.cache import Cache, cache_key
from engine.ingest import ResolvedRepo
from engine.models import Project, RepoRef

_FIX = Path(__file__).resolve().parent / "fixtures" / "analyze"


def _project():
    return Project(
        id="t",
        name="t",
        repos=[
            RepoRef(url="u-ui", folder="ui", branch="main"),
            RepoRef(url="u-api", folder="api", branch="master"),
        ],
    )


def _fake_ingest(monkeypatch):
    def fake(project, workspace, branch_overrides=None):
        return [
            ResolvedRepo(url="u-ui", folder="ui", branch="main", sha="uiSHA", path=str(_FIX / "ui")),
            ResolvedRepo(url="u-api", folder="api", branch="master", sha="apiSHA", path=str(_FIX / "api")),
        ]
    monkeypatch.setattr("engine.analyze.ingest", fake)


def test_analyze_builds_and_caches_model(tmp_path, monkeypatch):
    _fake_ingest(monkeypatch)
    cache = Cache(tmp_path / "cache")
    model = analyze(_project(), tmp_path / "ws", cache=cache, languages={"ui": "angular", "api": "python"})
    # one inbound endpoint from the api fixture
    assert any(e.path == "/edfx/v2/tools/customPd" for e in model.endpoints)
    # config /edfx/v2 prefixes the route -> one cross-repo flow
    assert len(model.flows) == 1
    # resolved shas flow into the cache key
    cached = cache.get(cache_key(model.project))
    assert cached == model
    assert model.project.repos[0].sha in ("uiSHA", "apiSHA")


def test_analyze_autodetects_language(tmp_path, monkeypatch):
    _fake_ingest(monkeypatch)
    # api fixture dir has no requirements.txt; add marker so detection picks python
    (_FIX / "api" / "main.py").write_text("", encoding="utf-8")
    try:
        model = analyze(_project(), tmp_path / "ws")  # no languages -> detect
        assert any(e.path == "/edfx/v2/tools/customPd" for e in model.endpoints)
    finally:
        (_FIX / "api" / "main.py").unlink()
