"""Extract FastAPI inbound routes: APIRouter(prefix=...) + @<var>.<verb>("path")."""

from __future__ import annotations

from pathlib import Path

from engine.models import CodeRef, Endpoint
from engine.parsers._support import python_parser, str_literal, text, walk

_VERBS = {"get", "post", "put", "delete", "patch"}


def _router_prefixes(root) -> dict[str, str]:
    """Map each `x = APIRouter(prefix="...")` variable to its prefix ("" if none)."""
    prefixes: dict[str, str] = {}
    for node in walk(root):
        if node.type != "assignment":
            continue
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if left is None or right is None or right.type != "call":
            continue
        fn = right.child_by_field_name("function")
        if fn is None or text(fn) != "APIRouter":
            continue
        prefix = ""
        args = right.child_by_field_name("arguments")
        if args is not None:
            for arg in args.children:
                if arg.type != "keyword_argument":
                    continue
                name = arg.child_by_field_name("name")
                value = arg.child_by_field_name("value")
                if name is not None and value is not None and text(name) == "prefix":
                    prefix = str_literal(value)
        prefixes[text(left)] = prefix
    return prefixes


def _decorator_route(dec, prefixes):
    """Return (METHOD, full_path) for a matching @<router>.<verb>("path") decorator."""
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
        for a in args.children:
            if a.type == "string":
                path = str_literal(a)
                break
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


def extract_fastapi_routes(repo_path, repo: str) -> list[Endpoint]:
    repo_root = Path(repo_path)
    parser = python_parser()
    endpoints: list[Endpoint] = []
    for py in sorted(repo_root.rglob("*.py")):
        source = py.read_bytes()
        root = parser.parse(source).root_node
        prefixes = _router_prefixes(root)
        if not prefixes:
            continue
        rel = py.relative_to(repo_root).as_posix()
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
                    route = _decorator_route(dec, prefixes)
                    if route:
                        break
            if route is None:
                continue
            method, path = route
            row = fn_def.start_point[0]
            snippet = lines[row].strip() if row < len(lines) else ""
            ref = CodeRef(repo=repo, file=rel, line=row + 1, snippet=snippet)
            endpoints.append(
                Endpoint(
                    id=f"{repo}:{method}:{path}",
                    repo=repo,
                    method=method,
                    path=path,
                    handler_ref=ref,
                    language="python",
                )
            )
    return endpoints
