import pytest
from pydantic import ValidationError

from engine.models import CodeRef, Endpoint, Flow, FlowEdge, FlowNode


def test_coderef_round_trips():
    ref = CodeRef(repo="edfx-api", file="src/routes/entity.ts", line=42, snippet="router.get(...)")
    assert ref.line == 42
    assert CodeRef.model_validate(ref.model_dump()) == ref


def test_endpoint_serializes_camelcase_handler_ref():
    ref = CodeRef(repo="edfx-api", file="a.ts", line=1, snippet="x")
    ep = Endpoint(
        id="ep1",
        repo="edfx-api",
        method="GET",
        path="/v2/entities/{id}",
        handler_ref=ref,
        language="typescript",
    )
    dumped = ep.model_dump(by_alias=True)
    assert dumped["handlerRef"]["file"] == "a.ts"
    # Round-trips back from camelCase JSON
    assert Endpoint.model_validate(dumped) == ep


def test_flowedge_uses_from_to_aliases():
    edge = FlowEdge(from_node="a", to_node="b", kind="http", confidence=0.9)
    dumped = edge.model_dump(by_alias=True)
    assert dumped["from"] == "a" and dumped["to"] == "b"
    assert FlowEdge.model_validate({"from": "a", "to": "b", "kind": "http", "confidence": 0.9}) == edge


def test_flowedge_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        FlowEdge(from_node="a", to_node="b", kind="http", confidence=1.5)


def test_flowedge_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        FlowEdge(from_node="a", to_node="b", kind="teleport", confidence=0.5)


def test_flow_round_trips():
    ref = CodeRef(repo="edfx-app-ui", file="App.tsx", line=10, snippet="api.get('/x')")
    node = FlowNode(id="n1", repo="edfx-app-ui", label="get entity", kind="ui", code_ref=ref)
    edge = FlowEdge(from_node="n1", to_node="n2", kind="http", confidence=1.0)
    flow = Flow(endpoint_id="ep1", nodes=[node], edges=[edge])
    dumped = flow.model_dump(by_alias=True)
    assert dumped["endpointId"] == "ep1"
    assert dumped["nodes"][0]["codeRef"]["file"] == "App.tsx"
    assert Flow.model_validate(dumped) == flow
