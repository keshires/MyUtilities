"""Extract FastAPI inbound routes: APIRouter(prefix=...) + @<var>.<verb>("path")."""

from __future__ import annotations

from pathlib import Path

from engine.models import CodeRef, Endpoint
from engine.parsers._consts import build_const_map, resolve_expr
from engine.parsers._support import python_parser, text, walk

_VERBS = {"get", "post", "put", "delete", "patch"}


def build_include_prefixes(repo_root, consts) -> dict[str, str]:
    """Map a router variable name to a mount prefix from `<obj>.include_router(VAR, prefix=...)`.

    Only handles identifier router refs (e.g. `loan_v2_router`); attribute refs like
    `api.router` are skipped (would need import resolution).
    """
    parser = python_parser()
    out: dict[str, str] = {}
    for py in sorted(Path(repo_root).rglob("*.py")):
        root = parser.parse(py.read_bytes()).root_node
        for node in walk(root):
            if node.type != "call":
                continue
            fn = node.child_by_field_name("function")
            if fn is None or fn.type != "attribute":
                continue
            attr = fn.child_by_field_name("attribute")
            if attr is None or text(attr) != "include_router":
                continue
            args = node.child_by_field_name("arguments")
            if args is None:
                continue
            reals = [a for a in args.children if a.type not in ("(", ")", ",")]
            if not reals or reals[0].type != "identifier":
                continue
            router_name = text(reals[0])
            for a in reals:
                if a.type == "keyword_argument":
                    name = a.child_by_field_name("name")
                    if name is not None and text(name) == "prefix":
                        resolved = resolve_expr(a.child_by_field_name("value"), consts)
                        if resolved:
                            out[router_name] = resolved
    return out


def _router_prefixes(root, consts, include_prefixes) -> dict[str, str]:
    """Map each `x = APIRouter(prefix=...)` variable to its effective prefix.

    effective = mount prefix (from include_router) + the router's own prefix.
    """
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
        own = ""
        args = right.child_by_field_name("arguments")
        if args is not None:
            for arg in args.children:
                if arg.type != "keyword_argument":
                    continue
                name = arg.child_by_field_name("name")
                value = arg.child_by_field_name("value")
                if name is not None and value is not None and text(name) == "prefix":
                    resolved = resolve_expr(value, consts)
                    if resolved is not None:
                        own = resolved
        var = text(left)
        prefixes[var] = include_prefixes.get(var, "") + own
    return prefixes


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


def extract_fastapi_routes(repo_path, repo: str, consts: dict | None = None) -> list[Endpoint]:
    repo_root = Path(repo_path)
    parser = python_parser()
    if consts is None:
        consts = build_const_map(repo_root)
    include_prefixes = build_include_prefixes(repo_root, consts)
    endpoints: list[Endpoint] = []
    for py in sorted(repo_root.rglob("*.py")):
        source = py.read_bytes()
        root = parser.parse(source).root_node
        prefixes = _router_prefixes(root, consts, include_prefixes)
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
                    route = _decorator_route(dec, prefixes, consts)
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
