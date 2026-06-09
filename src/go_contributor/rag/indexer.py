"""AST-aware chunker. The unit of retrieval is a *symbol* (function, method,
type), not an arbitrary token window. This is the single most impactful design
choice in the RAG layer: when the LLM gets back a "chunk", it gets a whole,
compilable function with its qualified name and line range.

When a symbol is too big (rare in idiomatic Go but happens with generated
code), we fall back to a sliding window inside that symbol so we never exceed
``max_chunk_chars``."""

from __future__ import annotations

from dataclasses import dataclass

from ..tools import ast_go


@dataclass
class Chunk:
    file: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int
    code: str


def build_chunks(repo_path: str, max_chars: int = 4000) -> list[Chunk]:
    syms = ast_go.index_repo(repo_path)
    out: list[Chunk] = []
    for s in syms:
        if len(s.code) <= max_chars:
            out.append(
                Chunk(
                    file=s.file,
                    qualified_name=s.qualified_name,
                    kind=s.kind,
                    start_line=s.start_line,
                    end_line=s.end_line,
                    code=s.code,
                )
            )
            continue
        # Sliding window inside the oversized symbol so retrieval still has
        # a meaningful chunk to score. We tag the qualified name with a
        # part suffix so the LLM knows it's seeing a slice.
        lines = s.code.splitlines(keepends=True)
        chunk: list[str] = []
        size = 0
        part = 0
        start_line = s.start_line
        running_line = s.start_line
        for ln in lines:
            chunk.append(ln)
            size += len(ln)
            running_line += 1
            if size >= max_chars:
                out.append(
                    Chunk(
                        file=s.file,
                        qualified_name=f"{s.qualified_name}#part{part}",
                        kind=s.kind,
                        start_line=start_line,
                        end_line=running_line,
                        code="".join(chunk),
                    )
                )
                part += 1
                start_line = running_line
                chunk = []
                size = 0
        if chunk:
            out.append(
                Chunk(
                    file=s.file,
                    qualified_name=f"{s.qualified_name}#part{part}",
                    kind=s.kind,
                    start_line=start_line,
                    end_line=s.end_line,
                    code="".join(chunk),
                )
            )
    return out


def build_symbol_graph(repo_path: str) -> dict[str, set[str]]:
    """Map qualified-name → set of names called from inside that symbol.

    Used for the one-hop graph expansion in the hybrid retriever: if BM25/dense
    pulls function A and A calls B, we boost B's score so the LLM sees both."""
    syms = ast_go.index_repo(repo_path)
    name_set = {s.qualified_name for s in syms}
    short_to_qualified: dict[str, list[str]] = {}
    for s in syms:
        short = s.qualified_name.split(".")[-1]
        short_to_qualified.setdefault(short, []).append(s.qualified_name)

    graph: dict[str, set[str]] = {}
    for s in syms:
        edges: set[str] = set()
        for callee in (s.callees or []):
            if callee in short_to_qualified:
                for q in short_to_qualified[callee]:
                    if q != s.qualified_name:
                        edges.add(q)
        graph[s.qualified_name] = edges
    # Ensure every node exists
    for n in name_set:
        graph.setdefault(n, set())
    return graph
