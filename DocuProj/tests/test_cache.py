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
