from engine.parsers._support import python_parser, str_literal, text, walk


def test_python_parser_parses_and_helpers_work():
    parser = python_parser()
    tree = parser.parse(b'x = "hello"\n')
    root = tree.root_node
    assert root.type == "module"
    strings = [n for n in walk(root) if n.type == "string"]
    assert len(strings) == 1
    assert str_literal(strings[0]) == "hello"
    assert text(strings[0]).startswith('"')


from pathlib import Path

from engine.parsers.python_fastapi import extract_fastapi_routes

_FIX = Path(__file__).resolve().parent / "fixtures" / "py_fastapi"


def test_extract_fastapi_routes():
    eps = extract_fastapi_routes(_FIX, repo="edfx-api")
    routes = {(e.method, e.path) for e in eps}
    assert ("GET", "/entities/{id}") in routes
    assert ("POST", "/entities") in routes  # prefix + "" decorator path
    assert ("GET", "/health") in routes     # router with no prefix
    by_path = {e.path: e for e in eps}
    ep = by_path["/entities/{id}"]
    assert ep.language == "python"
    assert ep.handler_ref.file == "sample_router.py"
    assert ep.handler_ref.line >= 1
    assert "get_entity" in ep.handler_ref.snippet


from engine.parsers import parse


def test_parse_dispatches_python():
    facts = parse(_FIX, "python", repo="edfx-api")
    assert facts.language == "python"
    assert facts.repo == "edfx-api"
    assert len(facts.endpoints) == 3
    assert facts.outbound_calls == []


def test_parse_python_includes_outbound():
    # the py_http fixture has outbound calls; FastAPI fixture has none
    facts = parse(Path(__file__).resolve().parent / "fixtures" / "py_http", "python", repo="edfx-api")
    assert len(facts.outbound_calls) == 3


def test_extract_fastapi_routes_resolves_constants():
    eps = extract_fastapi_routes(Path(__file__).resolve().parent / "fixtures" / "py_fastapi_const", repo="svc")
    paths = {e.path for e in eps}
    assert "/entity/v1/resolve" in paths           # prefix const + path const
    assert "/entity/v1/entity/v1/bulk" in paths     # prefix const + (const + literal)


def test_extract_fastapi_path_kwarg_and_include_prefix():
    eps = extract_fastapi_routes(Path(__file__).resolve().parent / "fixtures" / "py_fastapi_include", repo="svc")
    paths = {e.path for e in eps}
    # path= kwarg (PFX + "/items") resolved AND include_router(r, prefix="/svc") applied
    assert "/svc/v1/items" in paths


def test_extract_fastapi_cross_file_include_graph():
    fix = Path(__file__).resolve().parent / "fixtures" / "py_include_graph"
    eps = extract_fastapi_routes(fix, repo="entity")
    paths = {e.path for e in eps}
    assert "/entity/v1/items" in paths   # app.include_router(api.router, prefix='/entity') -> api includes items_route
    assert "/loans/x" in paths            # app.include_router(loan_router, prefix='/loans')
