from pathlib import Path

from engine.parsers.ts_angular import extract_angular_outbound

_FIX = Path(__file__).resolve().parent / "fixtures" / "ts_angular"


def test_extract_config_urls():
    _outbound, configs = extract_angular_outbound(_FIX, repo="edfx-app-ui")
    by_key = {c.key: c.url for c in configs}
    assert by_key["edfxApiV2Url"] == "https://api.example.net/edfx/v2"
    assert by_key["entitySearchApiUrl"] == "https://api.example.net/entity/v1"
    cfg = next(c for c in configs if c.key == "edfxApiV2Url")
    assert cfg.code_ref.file == "environment.dev.ts"
    assert cfg.code_ref.line >= 1


def test_extract_outbound_calls():
    outbound, _configs = extract_angular_outbound(_FIX, repo="edfx-app-ui")
    methods = sorted(c.method for c in outbound)
    assert methods == ["GET", "POST"]
    get_call = next(c for c in outbound if c.method == "GET")
    assert "entities" in get_call.target
    assert get_call.code_ref.file == "entity.service.ts"
    assert get_call.code_ref.line >= 1


from engine.parsers import parse


def test_parse_dispatches_typescript():
    facts = parse(_FIX, "angular", repo="edfx-app-ui")
    assert facts.language == "typescript"
    assert len(facts.outbound_calls) == 2
    assert len(facts.config_urls) == 3
    assert facts.endpoints == []
