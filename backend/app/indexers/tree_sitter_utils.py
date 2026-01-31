from __future__ import annotations

from functools import lru_cache
from typing import Iterable, Iterator, Sequence

from tree_sitter import Node, Parser, Tree
from tree_sitter_language_pack import get_language


@lru_cache(maxsize=16)
def _get_parser(lang: str) -> Parser | None:
    try:
        language = get_language(lang)
    except Exception:
        return None
    parser = Parser()
    if hasattr(parser, "set_language"):
        parser.set_language(language)
    else:
        parser.language = language
    return parser


def parse_tree(lang: str, text: str) -> tuple[Tree | None, bytes]:
    data = text.encode("utf-8", errors="replace")
    parser = _get_parser(lang)
    if parser is None:
        return None, data
    try:
        return parser.parse(data), data
    except Exception:
        return None, data


def node_text(node: Node | None, data: bytes) -> str:
    if node is None:
        return ""
    try:
        return data[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
    except Exception:
        return ""


def iter_nodes(root: Node | None) -> Iterator[Node]:
    if root is None:
        return iter(())
    stack: list[Node] = [root]
    while stack:
        node = stack.pop()
        yield node
        children: Sequence[Node] = node.children or []
        for child in reversed(children):
            stack.append(child)


def first_child(node: Node | None, types: Iterable[str]) -> Node | None:
    if node is None:
        return None
    type_set = set(types)
    for ch in node.children:
        if ch.type in type_set:
            return ch
    return None
