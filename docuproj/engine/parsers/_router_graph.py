"""Cross-file router include graph: resolve module.router / imported-router refs and
accumulate each router's full mount prefix from the app's include_router chain.

full_prefix(child) = full_prefix(parent) + include_prefix + own_prefix(child)
Default (router never reached from an app mount) = its own APIRouter prefix.
"""

from __future__ import annotations

from pathlib import Path

from engine.parsers._consts import resolve_expr
from engine.parsers._support import python_parser, text, walk

_ROOT = ("<root>", "<app>")


def _module_to_file(repo_root: Path, dotted: str) -> str | None:
    parts = dotted.split(".")
    cand = repo_root.joinpath(*parts).with_suffix(".py")
    if cand.exists():
        return cand.relative_to(repo_root).as_posix()
    init = repo_root.joinpath(*parts, "__init__.py")
    if init.exists():
        return init.relative_to(repo_root).as_posix()
    return None


def _parse_imports(root):
    """name -> dotted module it refers to (`name.attr`), and name -> (pkg, original) for vars."""
    module_of: dict[str, str] = {}
    var_from: dict[str, tuple[str, str]] = {}
    for node in walk(root):
        if node.type == "import_from_statement":
            mod = node.child_by_field_name("module_name")
            if mod is None:
                continue
            pkg = text(mod)
            seen_import = False
            for c in node.children:
                if c.type == "import":
                    seen_import = True
                    continue
                if not seen_import:
                    continue
                if c.type == "dotted_name":
                    name = text(c)
                    module_of[name] = f"{pkg}.{name}"
                    var_from[name] = (pkg, name)
                elif c.type == "aliased_import":
                    orig = text(c.child_by_field_name("name"))
                    alias = text(c.child_by_field_name("alias"))
                    module_of[alias] = f"{pkg}.{orig}"
                    var_from[alias] = (pkg, orig)
        elif node.type == "import_statement":
            for c in node.children:
                if c.type == "aliased_import":
                    module_of[text(c.child_by_field_name("alias"))] = text(c.child_by_field_name("name"))
    return module_of, var_from


def _router_defs(root, consts):
    """In one file: {var: own_prefix} for `var = APIRouter(prefix=...)`."""
    defs = {}
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
                if arg.type == "keyword_argument":
                    name = arg.child_by_field_name("name")
                    value = arg.child_by_field_name("value")
                    if name is not None and value is not None and text(name) == "prefix":
                        r = resolve_expr(value, consts)
                        if r is not None:
                            own = r
        defs[text(left)] = own
    return defs


def _resolve_ref(expr, rel, module_of, var_from, nodes, repo_root):
    """Resolve a reference expression to a router node (file_rel, var), or None."""
    if expr is None:
        return None
    if expr.type == "identifier":
        name = text(expr)
        if (rel, name) in nodes:
            return (rel, name)
        if name in var_from:
            pkg, orig = var_from[name]
            f = _module_to_file(repo_root, pkg)
            if f is not None and (f, orig) in nodes:
                return (f, orig)
        return None
    if expr.type == "attribute":
        obj = expr.child_by_field_name("object")
        attr = expr.child_by_field_name("attribute")
        if obj is None or attr is None or obj.type != "identifier":
            return None
        mod = module_of.get(text(obj))
        if mod is None:
            return None
        f = _module_to_file(repo_root, mod)
        if f is not None and (f, text(attr)) in nodes:
            return (f, text(attr))
        return None
    return None


def build_full_prefixes(repo_path, consts) -> dict[tuple[str, str], str]:
    repo_root = Path(repo_path)
    parser = python_parser()

    nodes: dict[tuple[str, str], str] = {}          # (file, var) -> own prefix
    raw_includes = []                                # (rel, module_of, var_from, parent_expr, child_expr, prefix)
    file_imports: dict[str, tuple] = {}

    for py in sorted(repo_root.rglob("*.py")):
        rel = py.relative_to(repo_root).as_posix()
        root = parser.parse(py.read_bytes()).root_node
        for var, own in _router_defs(root, consts).items():
            nodes[(rel, var)] = own
        file_imports[rel] = _parse_imports(root)

    for py in sorted(repo_root.rglob("*.py")):
        rel = py.relative_to(repo_root).as_posix()
        root = parser.parse(py.read_bytes()).root_node
        module_of, var_from = file_imports[rel]
        for node in walk(root):
            if node.type != "call":
                continue
            fn = node.child_by_field_name("function")
            if fn is None or fn.type != "attribute":
                continue
            if text(fn.child_by_field_name("attribute") or fn) != "include_router":
                continue
            args = node.child_by_field_name("arguments")
            if args is None:
                continue
            reals = [a for a in args.children if a.type not in ("(", ")", ",")]
            if not reals:
                continue
            prefix = ""
            for a in reals:
                if a.type == "keyword_argument":
                    name = a.child_by_field_name("name")
                    if name is not None and text(name) == "prefix":
                        r = resolve_expr(a.child_by_field_name("value"), consts)
                        if r is not None:
                            prefix = r
            parent = _resolve_ref(fn.child_by_field_name("object"), rel, module_of, var_from, nodes, repo_root)
            child = _resolve_ref(reals[0], rel, module_of, var_from, nodes, repo_root)
            if child is not None:
                raw_includes.append((parent or _ROOT, child, prefix))

    # children adjacency
    children: dict[tuple, list] = {}
    for parent, child, prefix in raw_includes:
        children.setdefault(parent, []).append((child, prefix))

    full: dict[tuple[str, str], str] = {n: own for n, own in nodes.items()}  # default = own

    def visit(node_id, accumulated, seen):
        for child, prefix in children.get(node_id, []):
            if child in seen:
                continue
            seen = seen | {child}
            full[child] = accumulated + prefix + nodes.get(child, "")
            visit(child, full[child], seen)

    visit(_ROOT, "", {_ROOT})
    return full