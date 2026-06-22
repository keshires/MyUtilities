"""Resolve module-level string constants across a Python repo, for path extraction.

Many services build route paths / URLs from named constants
(e.g. `CLIENT_FINANCIALS_CONTEXT + VERSION_1 + "/x"`). This pass collects
module-level `NAME = "literal"` assignments and resolves identifier /
concatenation expressions through that map so literal-path matching works.
"""

from __future__ import annotations

from pathlib import Path

from engine.parsers._support import python_parser, str_literal, text


def build_const_map(repo_root) -> dict[str, str]:
    parser = python_parser()
    consts: dict[str, str] = {}
    for py in sorted(Path(repo_root).rglob("*.py")):
        root = parser.parse(py.read_bytes()).root_node
        for stmt in root.children:  # module-level statements only
            if stmt.type != "expression_statement":
                continue
            for child in stmt.children:
                if child.type != "assignment":
                    continue
                left = child.child_by_field_name("left")
                right = child.child_by_field_name("right")
                if left is not None and right is not None and left.type == "identifier" and right.type == "string":
                    consts.setdefault(text(left), str_literal(right))
    return consts


def resolve_expr(node, consts: dict[str, str]) -> str | None:
    """Resolve a string / identifier / `+`-concatenation node to a string, else None."""
    if node is None:
        return None
    if node.type == "string":
        return str_literal(node)
    if node.type == "identifier":
        return consts.get(text(node))
    if node.type == "binary_operator":
        left = resolve_expr(node.child_by_field_name("left"), consts)
        right = resolve_expr(node.child_by_field_name("right"), consts)
        if left is not None and right is not None:
            return left + right
    return None
