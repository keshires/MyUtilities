"""Extract Python persistence access: SQLAlchemy .query/.execute, raw SQL, psycopg."""

from __future__ import annotations

import re
from pathlib import Path

from engine.facts import DbAccess
from engine.models import CodeRef
from engine.parsers._support import python_parser, str_literal, text, walk

_DB_VERBS = {"query", "execute", "executemany"}
_SQL_RE = re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE)\b", re.IGNORECASE)
_TABLE_RE = re.compile(r"\b(?:FROM|INTO|UPDATE|JOIN)\s+([A-Za-z_][\w.]*)", re.IGNORECASE)


def _table(sql: str) -> str:
    m = _TABLE_RE.search(sql)
    return m.group(1) if m else sql.strip()[:60]


def extract_python_db(repo_path, repo: str, consts=None) -> list[DbAccess]:
    parser = python_parser()
    out: list[DbAccess] = []
    repo_root = Path(repo_path)
    for py in sorted(repo_root.rglob("*.py")):
        source = py.read_bytes()
        root = parser.parse(source).root_node
        rel = py.relative_to(repo_root).as_posix()
        lines = source.decode("utf-8", "replace").splitlines()
        seen_rows: set[int] = set()

        def _ref(row: int) -> CodeRef:
            return CodeRef(repo=repo, file=rel, line=row + 1,
                           snippet=lines[row].strip() if row < len(lines) else "")

        # 1. <x>.query(...) / <x>.execute(...) calls
        for node in walk(root):
            if node.type != "call":
                continue
            fn = node.child_by_field_name("function")
            if fn is None or fn.type != "attribute":
                continue
            attr = fn.child_by_field_name("attribute")
            if attr is None or text(attr) not in _DB_VERBS:
                continue
            args = node.child_by_field_name("arguments")
            first = None
            if args is not None:
                reals = [c for c in args.children if c.type not in ("(", ")", ",")]
                if reals:
                    first = reals[0]
            arg_text = text(first) if first is not None else ""
            row = node.start_point[0]
            if text(attr) == "query":
                engine, detail = "sqlalchemy", (arg_text or "?")
            else:
                lit = str_literal(first) if (first is not None and first.type == "string") else arg_text
                if _SQL_RE.search(lit):
                    engine, detail = "raw_sql", _table(lit)
                else:
                    engine, detail = "sqlalchemy", (arg_text or "?")
            out.append(DbAccess(engine=engine, detail=detail, code_ref=_ref(row)))
            seen_rows.add(row)

        # 2. standalone SQL string literals (not already captured at a call site)
        for node in walk(root):
            if node.type != "string":
                continue
            val = str_literal(node)
            if len(val) > 12 and _SQL_RE.search(val) and _TABLE_RE.search(val):
                row = node.start_point[0]
                if row in seen_rows:
                    continue
                seen_rows.add(row)
                out.append(DbAccess(engine="raw_sql", detail=_table(val), code_ref=_ref(row)))
    return out