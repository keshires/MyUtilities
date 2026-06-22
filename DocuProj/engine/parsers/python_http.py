"""Extract Python outbound HTTP calls: <client>.<verb>(target, ...)."""

from __future__ import annotations

from pathlib import Path

from engine.facts import OutboundCall
from engine.models import CodeRef
from engine.parsers._support import python_parser, text, walk

_VERBS = {"get", "post", "put", "delete", "patch"}
_CLIENT_HINTS = ("requests", "httpx", "aiohttp", "session", "client", "http")


def extract_python_outbound(repo_path, repo: str) -> list[OutboundCall]:
    parser = python_parser()
    out: list[OutboundCall] = []
    repo_root = Path(repo_path)
    for py in sorted(repo_root.rglob("*.py")):
        source = py.read_bytes()
        root = parser.parse(source).root_node
        rel = py.relative_to(repo_root).as_posix()
        lines = source.decode("utf-8", "replace").splitlines()
        for node in walk(root):
            if node.type != "call":
                continue
            fn = node.child_by_field_name("function")
            if fn is None or fn.type != "attribute":
                continue
            obj = fn.child_by_field_name("object")
            attr = fn.child_by_field_name("attribute")
            if obj is None or attr is None:
                continue
            verb = text(attr)
            if verb not in _VERBS or not any(h in text(obj).lower() for h in _CLIENT_HINTS):
                continue
            target = ""
            args = node.child_by_field_name("arguments")
            if args is not None:
                reals = [c for c in args.children if c.type not in ("(", ")", ",")]
                if reals:
                    target = text(reals[0])
            row = node.start_point[0]
            snippet = lines[row].strip() if row < len(lines) else ""
            out.append(
                OutboundCall(
                    method=verb.upper(),
                    target=target,
                    code_ref=CodeRef(repo=repo, file=rel, line=row + 1, snippet=snippet),
                )
            )
    return out
