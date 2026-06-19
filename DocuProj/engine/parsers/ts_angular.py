"""Extract Angular outbound facts: endPointConfig URL map + this.http.<verb>() calls."""

from __future__ import annotations

from pathlib import Path

from engine.facts import ConfigUrl, OutboundCall
from engine.models import CodeRef
from engine.parsers._support import str_literal, text, ts_parser, walk

_VERBS = {"get", "post", "put", "delete", "patch"}


def _config_urls(root, repo, rel, lines) -> list[ConfigUrl]:
    out: list[ConfigUrl] = []
    for node in walk(root):
        if node.type != "pair":
            continue
        key = node.child_by_field_name("key")
        value = node.child_by_field_name("value")
        if key is None or value is None or text(key) != "endPointConfig" or value.type != "object":
            continue
        for entry in walk(value):
            if entry.type != "pair":
                continue
            k = entry.child_by_field_name("key")
            v = entry.child_by_field_name("value")
            if k is None or v is None or v.type != "string":
                continue
            row = entry.start_point[0]
            snippet = lines[row].strip() if row < len(lines) else ""
            out.append(
                ConfigUrl(
                    key=text(k),
                    url=str_literal(v),
                    code_ref=CodeRef(repo=repo, file=rel, line=row + 1, snippet=snippet),
                )
            )
        break  # first endPointConfig only
    return out


def _outbound_calls(root, repo, rel, lines) -> list[OutboundCall]:
    out: list[OutboundCall] = []
    for node in walk(root):
        if node.type != "call_expression":
            continue
        fn = node.child_by_field_name("function")
        if fn is None or fn.type != "member_expression":
            continue
        obj = fn.child_by_field_name("object")
        prop = fn.child_by_field_name("property")
        if obj is None or prop is None:
            continue
        verb = text(prop)
        if verb not in _VERBS or "http" not in text(obj).lower():
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


def extract_angular_outbound(repo_path, repo: str):
    repo_root = Path(repo_path)
    parser = ts_parser()
    outbound: list[OutboundCall] = []
    configs: list[ConfigUrl] = []
    for ts in sorted(repo_root.rglob("*.ts")):
        if ts.name.endswith(".d.ts"):
            continue
        source = ts.read_text(encoding="utf-8", errors="replace")
        root = parser.parse(source.encode("utf-8")).root_node
        rel = ts.relative_to(repo_root).as_posix()
        lines = source.splitlines()
        outbound.extend(_outbound_calls(root, repo, rel, lines))
        configs.extend(_config_urls(root, repo, rel, lines))
    return outbound, configs
