from pathlib import Path

from engine.parsers.python_handlers import build_handler_provenance

_FIX = Path(__file__).resolve().parent / "fixtures" / "py_handlers"


def test_handler_provenance_follows_call_graph():
    prov = build_handler_provenance(_FIX, repo="svc")
    p = prov["svc:GET:/p/list"]
    # outbound + db are reached transitively through _fetch / _read helpers
    assert any(o.method == "GET" for o in p.outbound)
    assert any(d.engine == "sqlalchemy" and d.detail == "Thing" for d in p.db)