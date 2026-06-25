"""Extract FastAPI inbound routes: APIRouter + @<var>.<verb>(path | path=...).

Route prefixes (own APIRouter prefix + cross-file include_router mounts) come from
the router include graph (`_router_graph.build_full_prefixes`), so a route's path is
`full_prefix(router) + decorator_path`.
"""

from __future__ import annotations

from pathlib import Path

from engine.models import CodeRef, Endpoint
from engine.parsers._consts import build_const_map, resolve_expr
from engine.parsers._router_graph import build_full_prefixes
from engine.parsers._support import python_parser, text, walk

_VERBS = {"get", "post", "put", "delete", "patch"}


def _decorator_route(dec, prefixes, consts):
    """Return (METHOD, full_path) for a matching @<router>.<verb>(path) decorator."""
    calls = [c for c in dec.children if c.type == "call"]
    if not calls:
        return None
    call = calls[0]
    fn = call.child_by_field_name("function")
    if fn is None or fn.type != "attribute":
        return None
    obj = fn.child_by_field_name("object")
    attr = fn.child_by_field_name("attribute")
    if obj is None or attr is None:
        return None
    router, verb = text(obj), text(attr)
    if router not in prefixes or verb not in _VERBS:
        return None
    path = ""
    args = call.child_by_field_name("arguments")
    if args is not None:
        reals = [a for a in args.children if a.type not in ("(", ")", ",")]
        resolved = None
        if reals and reals[0].type != "keyword_argument":
            resolved = resolve_expr(reals[0], consts)  # positional path
        if resolved is None:
            for a in reals:  # or a `path=` keyword argument
                if a.type == "keyword_argument":
                    name = a.child_by_field_name("name")
                    if name is not None and text(name) == "path":
                        resolved = resolve_expr(a.child_by_field_name("value"), consts)
                        break
        if resolved is not None:
            path = resolved
    full = prefixes[router] + path
    return verb.upper(), (full or "/")


def _function_definition(decorated):
    fn = decorated.child_by_field_name("definition")
    if fn is not None and fn.type == "function_definition":
        return fn
    for child in decorated.children:
        if child.type == "function_definition":
            return child
    return None


def _iter_routes(repo_path, consts):
    """Yield (method, full_path, fn_def, rel, lines) for every FastAPI route in the repo."""
    repo_root = Path(repo_path)
    parser = python_parser()
    full_prefixes = build_full_prefixes(repo_root, consts)
    for py in sorted(repo_root.rglob("*.py")):
        source = py.read_bytes()
        root = parser.parse(source).root_node
        rel = py.relative_to(repo_root).as_posix()
        prefixes = {var: pfx for (f, var), pfx in full_prefixes.items() if f == rel}
        if not prefixes:
            continue
        lines = source.decode("utf-8", "replace").splitlines()
        for node in walk(root):
            if node.type != "decorated_definition":
                continue
            fn_def = _function_definition(node)
            if fn_def is None:
                continue
            route = None
            for dec in node.children:
                if dec.type == "decorator":
                    route = _decorator_route(dec, prefixes, consts)
                    if route:
                        break
            if route is None:
                continue
            method, path = route
            yield method, path, fn_def, rel, lines


def extract_fastapi_routes(repo_path, repo: str, consts: dict | None = None) -> list[Endpoint]:
    repo_root = Path(repo_path)
    if consts is None:
        consts = build_const_map(repo_root)
    endpoints: list[Endpoint] = []
    for method, path, fn_def, rel, lines in _iter_routes(repo_root, consts):
        row = fn_def.start_point[0]
        snippet = lines[row].strip() if row < len(lines) else ""
        ref = CodeRef(repo=repo, file=rel, line=row + 1, snippet=snippet)
        endpoints.append(
            Endpoint(id=f"{repo}:{method}:{path}", repo=repo, method=method, path=path,
                     handler_ref=ref, language="python")
        )
    return endpoints


def iter_route_handlers(repo_path, repo: str, consts: dict | None = None):
    """Yield (endpoint_id, handler_function_name) for every route — seeds the call graph."""
    repo_root = Path(repo_path)
    if consts is None:
        consts = build_const_map(repo_root)
    for method, path, fn_def, _rel, _lines in _iter_routes(repo_root, consts):
        name_node = fn_def.child_by_field_name("name")
        if name_node is not None:
            yield f"{repo}:{method}:{path}", text(name_node)