from engine.facts import DbAccess, HandlerProvenance, OutboundCall, RepoFacts
from engine.linker import trace_flows
from engine.models import CodeRef, Endpoint, Project, RepoRef


def _ref(repo):
    return CodeRef(repo=repo, file="f.py", line=1, snippet="x")


def _ep(repo, path):
    return Endpoint(id=f"{repo}:GET:{path}", repo=repo, method="GET", path=path,
                    handler_ref=_ref(repo), language="python")


def _facts():
    # gateway endpoint whose handler calls "/svc/data" downstream (no DB of its own)
    gw = RepoFacts(
        repo="edfx-api", language="python",
        endpoints=[_ep("edfx-api", "/p/list")],
        handler_provenance={
            "edfx-api:GET:/p/list": HandlerProvenance(
                outbound=[OutboundCall(method="GET", target="'/svc/data'", code_ref=_ref("edfx-api"))],
                db=[],
            )
        },
    )
    # downstream service endpoint whose handler reads the DB
    svc = RepoFacts(
        repo="edfx-tessera-service", language="python",
        endpoints=[_ep("edfx-tessera-service", "/svc/data")],
        handler_provenance={
            "edfx-tessera-service:GET:/svc/data": HandlerProvenance(
                outbound=[],
                db=[DbAccess(engine="sqlalchemy", detail="Portfolio", code_ref=_ref("edfx-tessera-service"))],
            )
        },
    )
    return [gw, svc]


def _project():
    return Project(id="p", name="p", repos=[
        RepoRef(url="a", folder="edfx-api", branch="master", sha="1"),
        RepoRef(url="b", folder="edfx-tessera-service", branch="main", sha="2"),
    ])


def test_trace_builds_forward_chain_to_datastore():
    model = trace_flows(_facts(), _project())
    flow = next(f for f in model.flows if f.endpoint_id == "edfx-api:GET:/p/list")
    kinds = sorted(n.kind for n in flow.nodes)
    # route (gateway) -> route (service) -> datastore
    assert kinds == ["datastore", "route", "route"]
    edge_kinds = sorted(e.kind for e in flow.edges)
    assert edge_kinds == ["db", "http"]
    # the datastore belongs to the downstream service
    ds = next(n for n in flow.nodes if n.kind == "datastore")
    assert ds.repo == "edfx-tessera-service"

import json


class _FakeBlock:
    def __init__(self, text):
        self.type = "text"; self.text = text


class _FakeResp:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeClient:
    class _M:
        def __init__(self, text):
            self._t = text
        def create(self, **kw):
            return _FakeResp(self._t)
    def __init__(self, text):
        self.messages = _FakeClient._M(text)


def test_trace_uses_claude_resolver_for_variable_targets():
    from engine.claude_resolver import ClaudeResolver
    # gateway handler calls downstream via a runtime VARIABLE (no literal path)
    gw = RepoFacts(
        repo="edfx-api", language="python",
        endpoints=[_ep("edfx-api", "/p/list")],
        handler_provenance={
            "edfx-api:GET:/p/list": HandlerProvenance(
                outbound=[OutboundCall(method="GET", target="url", code_ref=_ref("edfx-api"))],  # variable
                db=[],
            )
        },
    )
    svc = RepoFacts(
        repo="edfx-tessera-service", language="python",
        endpoints=[_ep("edfx-tessera-service", "/svc/data")],
        handler_provenance={
            "edfx-tessera-service:GET:/svc/data": HandlerProvenance(
                outbound=[], db=[DbAccess(engine="sqlalchemy", detail="Portfolio", code_ref=_ref("edfx-tessera-service"))],
            )
        },
    )
    # deterministic alone: variable target -> the gateway never reaches Tessera
    det = trace_flows([gw, svc], _project())
    det_gw = [f for f in det.flows if f.endpoint_id == "edfx-api:GET:/p/list"]
    assert not any(n.repo == "edfx-tessera-service" for f in det_gw for n in f.nodes)

    # with Claude resolver: the variable call resolves to the Tessera endpoint
    payload = json.dumps({"links": [
        {"source_index": 0, "endpoint_id": "edfx-tessera-service:GET:/svc/data", "confidence": 0.8}
    ]})
    model = trace_flows([gw, svc], _project(), resolver=ClaudeResolver(client=_FakeClient(payload)))
    flow = next(f for f in model.flows if f.endpoint_id == "edfx-api:GET:/p/list")
    kinds = sorted(n.kind for n in flow.nodes)
    assert kinds == ["datastore", "route", "route"]  # gateway -> Tessera -> datastore
    http_edge = next(e for e in flow.edges if e.kind == "http")
    assert http_edge.confidence == 0.8
