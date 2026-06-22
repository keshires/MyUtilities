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


from engine.facts import ConfigUrl, RepoFacts
from engine.linker import link
from engine.models import Project, RepoRef


def _project():
    return Project(
        id="edfx-flow",
        name="EDFX Flow",
        repos=[
            RepoRef(url="u1", folder="edfx-app-ui", branch="main", sha="a"),
            RepoRef(url="u2", folder="edfx-api", branch="master", sha="b"),
        ],
    )


def _facts():
    ui = RepoFacts(
        repo="edfx-app-ui",
        language="typescript",
        config_urls=[ConfigUrl(key="edfxApiV2Url", url="https://h/edfx/v2", code_ref=_ref())],
    )
    api = RepoFacts(
        repo="edfx-api",
        language="python",
        endpoints=[_endpoint("/edfx/v2/tools/customPd"), _endpoint("/other/y")],
    )
    return [ui, api]


def test_link_builds_analysis_model():
    model = link(_facts(), _project())
    assert len(model.endpoints) == 2          # all inbound endpoints listed
    assert len(model.flows) == 1              # only the /edfx/v2 one is reachable
    flow = model.flows[0]
    assert flow.endpoint_id == "edfx-api:GET:/edfx/v2/tools/customPd"
    kinds = sorted(n.kind for n in flow.nodes)
    assert kinds == ["route", "ui"]
    ui_node = next(n for n in flow.nodes if n.kind == "ui")
    assert ui_node.label == "edfxApiV2Url"
    assert flow.edges[0].kind == "http"
    assert flow.edges[0].confidence == 0.5
    assert flow.edges[0].from_node == ui_node.id


def test_link_respects_custom_resolver_seam():
    class MatchAll:
        def score(self, query):
            return 1.0

    model = link(_facts(), _project(), resolver=MatchAll())
    assert len(model.flows) == 2              # every endpoint now links
    assert all(e.confidence == 1.0 for f in model.flows for e in f.edges)


from engine.linker import target_path


def test_target_path_extracts_literal_only():
    assert target_path("'/entity/v1/resolve'") == "/entity/v1/resolve"
    assert target_path("base + '/financials/client/v1/ratios'") == "/financials/client/v1/ratios"
    assert target_path("url") == ""  # bare variable -> no path


def test_link_connects_outbound_to_downstream_route():
    from engine.facts import OutboundCall, RepoFacts

    gateway = RepoFacts(
        repo="edfx-api",
        language="python",
        endpoints=[_endpoint("/edfx/v2/x")],  # gateway's own route
        outbound_calls=[
            OutboundCall(method="POST", target="'/entity/v1/resolve'", code_ref=_ref())
        ],
    )
    entity = RepoFacts(
        repo="edfx_entity_api",
        language="python",
        endpoints=[Endpoint(id="edfx_entity_api:POST:/entity/v1/resolve", repo="edfx_entity_api",
                            method="POST", path="/entity/v1/resolve", handler_ref=_ref(), language="python")],
    )
    project = Project(id="p", name="p", repos=[
        RepoRef(url="a", folder="edfx-api", branch="master", sha="1"),
        RepoRef(url="b", folder="edfx_entity_api", branch="main", sha="2"),
    ])
    model = link([gateway, entity], project)
    flow = next(f for f in model.flows if f.endpoint_id == "edfx_entity_api:POST:/entity/v1/resolve")
    kinds = sorted(n.kind for n in flow.nodes)
    assert kinds == ["outbound", "route"]
    assert flow.edges[0].kind == "http"
    # gateway's own /edfx/v2/x has no inbound source -> no flow
    assert not any(f.endpoint_id == "edfx-api:GET:/edfx/v2/x" for f in model.flows)


def test_target_path_accepts_bare_resolved_path():
    assert target_path("/entity/v1/resolve") == "/entity/v1/resolve"
