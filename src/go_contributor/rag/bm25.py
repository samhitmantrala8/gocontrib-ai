"""BM25 over symbol-level chunks. We tokenise on a Go-aware split: identifiers
(camelCase + snake_case + dotted), keywords, and string literals — all lowered.
Pure lexical retrieval is shockingly strong on Go because issue authors
usually quote the exact symbol name."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from .indexer import Chunk


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _split_camel(tok: str) -> list[str]:
    parts = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z]|$)", tok)
    return [p.lower() for p in parts] if parts else [tok.lower()]


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        tok = m.group(0)
        out.append(tok.lower())
        # Add camel-case sub-tokens so "BindJSON" indexes as ["bindjson","bind","json"]
        sub = _split_camel(tok)
        if sub != [tok.lower()]:
            out.extend(sub)
    return out


@dataclass
class Hit:
    chunk: Chunk
    score: float


class BM25Index:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        # Index: chunk text + qualified name + file path
        docs = [
            tokenize(c.code) + tokenize(c.qualified_name) + tokenize(c.file.replace("/", " "))
            for c in chunks
        ]
        self._bm25 = BM25Okapi(docs) if docs else None

    def query(self, q: str, top_k: int = 20) -> list[Hit]:
        if self._bm25 is None or not self.chunks:
            return []
        tokens = tokenize(q)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(
            zip(self.chunks, scores), key=lambda x: x[1], reverse=True
        )[:top_k]
        return [Hit(chunk=c, score=float(s)) for c, s in ranked if s > 0]
