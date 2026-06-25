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