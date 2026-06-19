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
