from engine.facts import ConfigUrl, OutboundCall, RepoFacts
from engine.models import CodeRef


def test_repofacts_defaults_empty():
    facts = RepoFacts(repo="edfx-api", language="python")
    assert facts.endpoints == []
    assert facts.outbound_calls == []
    assert facts.config_urls == []


def test_outbound_and_config_round_trip():
    ref = CodeRef(repo="edfx-app-ui", file="a.ts", line=3, snippet="this.http.get(url)")
    call = OutboundCall(method="GET", target="`${base}/x`", code_ref=ref)
    cfg = ConfigUrl(key="edfxApiV2Url", url="https://h/edfx/v2", code_ref=ref)
    facts = RepoFacts(repo="edfx-app-ui", language="typescript", outbound_calls=[call], config_urls=[cfg])
    assert RepoFacts.model_validate(facts.model_dump()) == facts
