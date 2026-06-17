from engine.models import CodeRef, Endpoint


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
