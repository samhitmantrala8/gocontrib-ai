"""Tree-sitter Go: extract symbol-level chunks (functions, methods, types) and
basic call-graph edges. Used both for AST-aware RAG chunking and for the
patcher's "show me the symbol called X" tool."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .fs import walk_go_files


@dataclass
class Symbol:
    file: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int
    code: str
    receiver: Optional[str] = None
    callees: list[str] = None       # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Tree-sitter loader (lazy — keeps test imports cheap)
# ---------------------------------------------------------------------------

_LANG = None
_PARSER = None


def _load_parser():
    global _LANG, _PARSER
    if _PARSER is not None:
        return _PARSER
    try:
        import tree_sitter_go
        from tree_sitter import Language, Parser
    except ImportError as e:                                            # noqa: BLE001
        raise RuntimeError(
            "tree-sitter / tree-sitter-go not installed. "
            "Run: pip install tree-sitter tree-sitter-go"
        ) from e

    _LANG = Language(tree_sitter_go.language())
    parser = Parser(_LANG)
    _PARSER = parser
    return parser


# ---------------------------------------------------------------------------
# Symbol extraction
# ---------------------------------------------------------------------------

def parse_file(repo_path: str, rel: str) -> list[Symbol]:
    p = Path(repo_path) / rel
    try:
        src = p.read_bytes()
    except OSError:
        return []
    if not src.strip():
        return []

    parser = _load_parser()
    tree = parser.parse(src)
    return _extract(tree.root_node, src, rel)


def _node_text(node, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _named_child_by_field(node, field: str):
    return node.child_by_field_name(field)


def _extract(root, src: bytes, rel: str) -> list[Symbol]:
    syms: list[Symbol] = []

    def add(node, kind: str, name: str, receiver: Optional[str] = None) -> None:
        code = _node_text(node, src)
        syms.append(
            Symbol(
                file=rel,
                qualified_name=(f"{receiver}.{name}" if receiver else name),
                kind=kind,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                code=code,
                receiver=receiver,
                callees=_callees(node, src),
            )
        )

    def visit(node):
        t = node.type
        if t == "function_declaration":
            name_node = _named_child_by_field(node, "name")
            if name_node is not None:
                add(node, "function", _node_text(name_node, src))
        elif t == "method_declaration":
            name_node = _named_child_by_field(node, "name")
            recv_node = _named_child_by_field(node, "receiver")
            recv_type = _receiver_type_name(recv_node, src) if recv_node else None
            if name_node is not None:
                add(node, "method", _node_text(name_node, src), receiver=recv_type)
        elif t == "type_declaration":
            for child in node.children:
                if child.type == "type_spec":
                    name_node = _named_child_by_field(child, "name")
                    if name_node is not None:
                        add(node, "type", _node_text(name_node, src))
        for child in node.children:
            visit(child)

    visit(root)
    return syms


def _receiver_type_name(recv_node, src: bytes) -> Optional[str]:
    # receiver -> parameter_list -> parameter_declaration -> type
    for p in recv_node.children:
        if p.type == "parameter_declaration":
            type_node = _named_child_by_field(p, "type")
            if type_node is None:
                continue
            t = _node_text(type_node, src).strip()
            return t.lstrip("*")
    return None


def _callees(node, src: bytes) -> list[str]:
    out: list[str] = []

    def visit(n):
        if n.type == "call_expression":
            fn = _named_child_by_field(n, "function")
            if fn is not None:
                txt = _node_text(fn, src).strip()
                # Take the last identifier in foo.bar.Baz to keep the graph dense
                tail = txt.split(".")[-1]
                if tail.isidentifier():
                    out.append(tail)
        for c in n.children:
            visit(c)

    visit(node)
    return out


# ---------------------------------------------------------------------------
# Repo-wide indexing
# ---------------------------------------------------------------------------

def index_repo(repo_path: str) -> list[Symbol]:
    out: list[Symbol] = []
    for rel in walk_go_files(repo_path):
        out.extend(parse_file(repo_path, rel))
    return out


def parse_ok(source: str) -> bool:
    """Cheap syntactic check: does this Go source parse without errors?
    Used by the guardrail to reject patches that introduce parse errors."""
    if not source.strip():
        return True
    parser = _load_parser()
    tree = parser.parse(source.encode("utf-8"))

    def has_error(n) -> bool:
        if n.has_error or n.type == "ERROR":
            return True
        return any(has_error(c) for c in n.children)

    return not has_error(tree.root_node)
