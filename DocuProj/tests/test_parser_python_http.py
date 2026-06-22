from pathlib import Path

from engine.parsers.python_http import extract_python_outbound

_FIX = Path(__file__).resolve().parent / "fixtures" / "py_http"


def test_extract_python_outbound():
    calls = extract_python_outbound(_FIX, repo="edfx-api")
    methods = sorted(c.method for c in calls)
    # POST (requests), GET (requests var), GET (session) — not_http excluded
    assert methods == ["GET", "GET", "POST"]
    post = next(c for c in calls if c.method == "POST")
    assert "/entity/v1/resolve" in post.target
    assert post.code_ref.file == "client.py"
    assert post.code_ref.line >= 1


def test_outbound_resolves_constant_target(tmp_path):
    from engine.linker import target_path
    (tmp_path / "c.py").write_text(
        'import requests\nP = "/svc/v1/run"\ndef f():\n    return requests.post(P)\n', encoding="utf-8"
    )
    calls = extract_python_outbound(tmp_path, repo="g")
    assert any(target_path(c.target) == "/svc/v1/run" for c in calls)
