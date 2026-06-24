import json

from engine.claude_resolver import ClaudeResolver, ResolvedLink
from engine.facts import OutboundCall
from engine.models import CodeRef, Endpoint


def _ref():
    return CodeRef(repo="edfx-api", file="client.py", line=10, snippet="requests.post(url)")


def _endpoint(eid="edfx_entity_api:POST:/entity/v1/resolve"):
    return Endpoint(id=eid, repo="edfx_entity_api", method="POST", path="/entity/v1/resolve",
                    handler_ref=_ref(), language="python")


class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResp:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, text):
        self._text = text
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return _FakeResp(self._text)


class _FakeClient:
    def __init__(self, text):
        self.messages = _FakeMessages(text)


def test_resolve_returns_links():
    payload = json.dumps({"links": [
        {"source_index": 0, "endpoint_id": "edfx_entity_api:POST:/entity/v1/resolve", "confidence": 0.9}
    ]})
    resolver = ClaudeResolver(client=_FakeClient(payload))
    links = resolver.resolve([OutboundCall(method="POST", target="url", code_ref=_ref())], [_endpoint()])
    assert links == [ResolvedLink(source_index=0, endpoint_id="edfx_entity_api:POST:/entity/v1/resolve", confidence=0.9)]


def test_resolve_drops_unknown_endpoint_ids():
    payload = json.dumps({"links": [
        {"source_index": 0, "endpoint_id": "does-not-exist", "confidence": 0.8}
    ]})
    resolver = ClaudeResolver(client=_FakeClient(payload))
    links = resolver.resolve([OutboundCall(method="POST", target="url", code_ref=_ref())], [_endpoint()])
    assert links == []


def test_resolve_empty_inputs_skips_api_call():
    fake = _FakeClient("{}")
    resolver = ClaudeResolver(client=fake)
    assert resolver.resolve([], [_endpoint()]) == []
    assert resolver.resolve([OutboundCall(method="GET", target="x", code_ref=_ref())], []) == []
    assert fake.messages.calls == 0

from engine.facts import RepoFacts
from engine.linker import enrich_flows, link
from engine.models import Project, RepoRef


def test_enrich_flows_adds_claude_links():
    gateway = RepoFacts(
        repo="edfx-api",
        language="python",
        endpoints=[_endpoint("edfx-api:GET:/x")],
        outbound_calls=[OutboundCall(method="POST", target="url", code_ref=_ref())],  # variable target
    )
    entity = RepoFacts(repo="edfx_entity_api", language="python", endpoints=[_endpoint()])
    project = Project(id="p", name="p", repos=[
        RepoRef(url="a", folder="edfx-api", branch="master", sha="1"),
        RepoRef(url="b", folder="edfx_entity_api", branch="main", sha="2"),
    ])
    facts = [gateway, entity]
    model = link(facts, project)
    # deterministic: variable target -> entity endpoint has no flow
    assert not any(f.endpoint_id == "edfx_entity_api:POST:/entity/v1/resolve" for f in model.flows)

    payload = json.dumps({"links": [
        {"source_index": 0, "endpoint_id": "edfx_entity_api:POST:/entity/v1/resolve", "confidence": 0.7}
    ]})
    enriched = enrich_flows(model, facts, ClaudeResolver(client=_FakeClient(payload)))
    flow = next(f for f in enriched.flows if f.endpoint_id == "edfx_entity_api:POST:/entity/v1/resolve")
    kinds = sorted(n.kind for n in flow.nodes)
    assert kinds == ["outbound", "route"]
    assert flow.edges[0].kind == "http"
    assert flow.edges[0].confidence == 0.7
