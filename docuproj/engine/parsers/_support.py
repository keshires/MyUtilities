"""Shared tree-sitter setup and node helpers (node-traversal API, version-stable)."""

from __future__ import annotations

from functools import lru_cache

import tree_sitter_python as tsp
import tree_sitter_typescript as tst
from tree_sitter import Language, Parser


@lru_cache(maxsize=1)
def python_parser() -> Parser:
    return Parser(Language(tsp.language()))


@lru_cache(maxsize=1)
def ts_parser() -> Parser:
    return Parser(Language(tst.language_typescript()))


def walk(node):
    """Yield node and all descendants, depth-first."""
    yield node
    for child in node.children:
        yield from walk(child)


def text(node) -> str:
    return node.text.decode("utf-8", "replace")


def str_literal(node) -> str:
    """Literal value of a string node: prefer the content child, else strip quotes."""
    for child in node.children:
        if child.type in ("string_content", "string_fragment"):
            return text(child)
    raw = text(node)
    if len(raw) >= 2 and raw[0] in "\"'`" and raw[-1] in "\"'`":
        return raw[1:-1]
    return raw
