"""Hybrid retriever: weighted fusion of BM25, dense, and one-hop graph
expansion. Each contribution is normalised to [0,1] before fusion so the
weights in ``config.yaml`` are intuitive (they don't depend on the absolute
score scale of the underlying ranker)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..state import RetrievedChunk
from .bm25 import BM25Index, Hit
from .dense import DenseIndex
from .indexer import Chunk


@dataclass
class HybridConfig:
    bm25_weight: float = 0.4
    dense_weight: float = 0.5
    graph_weight: float = 0.1
    top_k: int = 12


def _normalise(hits: list[Hit]) -> dict[str, float]:
    if not hits:
        return {}
    max_s = max(h.score for h in hits) or 1.0
    return {_key(h.chunk): h.score / max_s for h in hits}


def _key(c: Chunk) -> str:
    return f"{c.file}::{c.qualified_name}::{c.start_line}"


class HybridRetriever:
    def __init__(
        self,
        chunks: list[Chunk],
        symbol_graph: dict[str, set[str]],
        *,
        bm25: Optional[BM25Index] = None,
        dense: Optional[DenseIndex] = None,
        cfg: Optional[HybridConfig] = None,
    ):
        self.chunks = chunks
        self._by_key = {_key(c): c for c in chunks}
        self._by_qual: dict[str, list[Chunk]] = {}
        for c in chunks:
            self._by_qual.setdefault(c.qualified_name, []).append(c)
        self.graph = symbol_graph
        self.cfg = cfg or HybridConfig()
        self.bm25 = bm25 or BM25Index(chunks)
        self.dense = dense

    def query(self, q: str) -> list[RetrievedChunk]:
        scores: dict[str, float] = {}
        sources: dict[str, list[str]] = {}

        # 1. BM25
        bm25_hits = self.bm25.query(q, top_k=self.cfg.top_k * 3)
        for k, s in _normalise(bm25_hits).items():
            scores[k] = scores.get(k, 0.0) + s * self.cfg.bm25_weight
            sources.setdefault(k, []).append("bm25")

        # 2. Dense (optional — system runs without it if the embedding model
        # can't load, e.g. offline first run with no cached weights).
        if self.dense is not None and self.cfg.dense_weight > 0:
            try:
                dense_hits = self.dense.query(q, top_k=self.cfg.top_k * 3)
                for k, s in _normalise(dense_hits).items():
                    scores[k] = scores.get(k, 0.0) + s * self.cfg.dense_weight
                    sources.setdefault(k, []).append("dense")
            except Exception:                                           # noqa: BLE001
                # Dense is enrichment, not load-bearing.
                pass

        # 3. Graph expansion: for each chunk currently in the top-K, add a
        # boost to its first-degree neighbours so their callees / callers get
        # surfaced even when neither lexical nor semantic retrieval pulled them.
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[: self.cfg.top_k]
        boost: dict[str, float] = {}
        for k, base_score in ranked:
            chunk = self._by_key[k]
            for neighbour in self.graph.get(chunk.qualified_name, set()):
                for nc in self._by_qual.get(neighbour, []):
                    nk = _key(nc)
                    if nk in scores:
                        continue
                    boost[nk] = max(
                        boost.get(nk, 0.0),
                        base_score * 0.5 * self.cfg.graph_weight,
                    )
        for k, s in boost.items():
            scores[k] = scores.get(k, 0.0) + s
            sources.setdefault(k, []).append("graph")

        # Final ranking
        final = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[: self.cfg.top_k]
        out: list[RetrievedChunk] = []
        for k, s in final:
            c = self._by_key[k]
            out.append(
                RetrievedChunk(
                    file=c.file,
                    qualified_name=c.qualified_name,
                    kind=c.kind,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    code=c.code,
                    score=float(s),
                    sources=sources.get(k, []),
                )
            )
        return out
