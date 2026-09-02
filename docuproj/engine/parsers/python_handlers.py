"""Handler-scoped provenance: associate each route's reachable outbound calls + DB
accesses with the endpoint, following a name-based intra-repo call graph.

The call graph is a deterministic approximation — callees are matched by bare function
name across the repo (method/import indirection is best-effort). Ambiguous service hops
are resolved later by the Claude resolver.
"""

from __future__ import annotations

import re
from pathlib import Path

from engine.facts import DbAccess, HandlerProvenance, OutboundCall
from engine.models import CodeRef
from engine.parsers._consts import build_const_map, resolve_expr
from engine.parsers._support import python_parser, str_literal, text, walk
from engine.parsers.python_fastapi import iter_route_handlers

_VERBS = {"get", "post", "put", "delete", "patch"}
_CLIENT_HINTS = ("requests", "httpx", "aiohttp", "session", "client", "http")
_DB_VERBS = {"query", "execute", "executemany"}
_SQL_RE = re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE)\b", re.IGNORECASE)
_TABLE_RE = re.compile(r"\b(?:FROM|INTO|UPDATE|JOIN)\s+([A-Za-z_][\w.]*)", re.IGNORECASE)


def _ref(repo, rel, lines, row):
    return CodeRef(repo=repo, file=rel, line=row + 1, snippet=lines[row].strip() if row < len(lines) else "")


def _first_arg(call):
    args = call.child_by_field_name("arguments")
    if args is None:
        return None
    reals = [c for c in args.children if c.type not in ("(", ")", ",")]
    return reals[0] if reals else None


def _function_facts(root, consts, repo, rel, lines):
    """name -> {outbound: [OutboundCall], db: [DbAccess], callees: set[str]} for this file."""
    funcs: dict[str, dict] = {}
    for fn_def in (n for n in walk(root) if n.type == "function_definition"):
        name_node = fn_def.child_by_field_name("name")
        if name_node is None:
            continue
        fname = text(name_node)
        ob: list[OutboundCall] = []
        db: list[DbAccess] = []
        callees: set[str] = set()
        for n in walk(fn_def):
            if n.type != "call":
                continue
            fn = n.child_by_field_name("function")
            if fn is None:
                continue
            if fn.type == "identifier":
                callees.add(text(fn))
                continue
            if fn.type != "attribute":
                continue
            obj = fn.child_by_field_name("object")
            attr = fn.child_by_field_name("attribute")
            if attr is None:
                continue
            verb = text(attr)
            callees.add(verb)
            row = n.start_point[0]
            if obj is not None and verb in _VERBS and any(h in text(obj).lower() for h in _CLIENT_HINTS):
                first = _first_arg(n)
                target = (resolve_expr(first, consts) or text(first)) if first is not None else ""
                ob.append(OutboundCall(method=verb.upper(), target=target, code_ref=_ref(repo, rel, lines, row)))
            elif verb in _DB_VERBS:
                first = _first_arg(n)
                if verb == "query":
                    engine, detail = "sqlalchemy", (text(first) if first is not None else "?")
                else:
                    lit = str_literal(first) if (first is not None and first.type == "string") else (text(first) if first is not None else "")
                    if _SQL_RE.search(lit):
                        m = _TABLE_RE.search(lit)
                        engine, detail = "raw_sql", (m.group(1) if m else lit[:60])
                    else:
                        engine, detail = "sqlalchemy", (text(first) if first is not None else "?")
                db.append(DbAccess(engine=engine, detail=detail, code_ref=_ref(repo, rel, lines, row)))
        existing = funcs.setdefault(fname, {"outbound": [], "db": [], "callees": set()})
        existing["outbound"].extend(ob)
        existing["db"].extend(db)
        existing["callees"].update(callees)
    return funcs


def build_handler_provenance(repo_path, repo: str, consts: dict | None = None) -> dict[str, HandlerProvenance]:
    repo_root = Path(repo_path)
    parser = python_parser()
    if consts is None:
        consts = build_const_map(repo_root)

    # repo-wide function -> facts map (callees resolved by bare name across files)
    global_funcs: dict[str, dict] = {}
    for py in sorted(repo_root.rglob("*.py")):
        source = py.read_bytes()
        root = parser.parse(source).root_node
        rel = py.relative_to(repo_root).as_posix()
        lines = source.decode("utf-8", "replace").splitlines()
        for fname, facts in _function_facts(root, consts, repo, rel, lines).items():
            g = global_funcs.setdefault(fname, {"outbound": [], "db": [], "callees": set()})
            g["outbound"].extend(facts["outbound"])
            g["db"].extend(facts["db"])
            g["callees"].update(facts["callees"])

    provenance: dict[str, HandlerProvenance] = {}
    for endpoint_id, handler in iter_route_handlers(repo_root, repo, consts):
        ob: list[OutboundCall] = []
        db: list[DbAccess] = []
        seen: set[str] = set()
        stack = [handler]
        while stack:
            fname = stack.pop()
            if fname in seen:
                continue
            seen.add(fname)
            g = global_funcs.get(fname)
            if g is None:
                continue
            ob.extend(g["outbound"])
            db.extend(g["db"])
            stack.extend(g["callees"])
        provenance[endpoint_id] = HandlerProvenance(outbound=ob, db=db)
    return provenance