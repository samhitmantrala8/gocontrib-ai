"""Retriever: build (or reuse) the hybrid index and pull the top-K symbols
relevant to the issue. Also runs the convention learner and stashes its
output in state for the patcher prompt."""

from __future__ import annotations

from ..rag.bm25 import BM25Index
from ..rag.convention_learner import learn as learn_conventions
from ..rag.dense import DenseIndex
from ..rag.hybrid import HybridConfig, HybridRetriever
from ..state import AgentState
from ..utils.logging import info, step, warn
from . import mapper as mapper_node
from ._common import get_llm, trace


def _build_retriever(repo_path: str, cfg: dict) -> HybridRetriever:
    cache = mapper_node.cached(repo_path)
    if "retriever" in cache:
        return cache["retriever"]

    chunks = cache["chunks"]
    graph = cache["graph"]
    bm25 = BM25Index(chunks)
    dense: DenseIndex | None = None
    if float(cfg.get("dense_weight", 0)) > 0:
        try:
            dense = DenseIndex(
                repo_path=repo_path,
                chunks=chunks,
                model_name=cfg.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2"),
            )
        except Exception as e:                                          # noqa: BLE001
            warn(f"dense retrieval disabled: {e}")
            dense = None

    retriever = HybridRetriever(
        chunks=chunks,
        symbol_graph=graph,
        bm25=bm25,
        dense=dense,
        cfg=HybridConfig(
            bm25_weight=float(cfg.get("bm25_weight", 0.4)),
            dense_weight=float(cfg.get("dense_weight", 0.5)),
            graph_weight=float(cfg.get("graph_weight", 0.1)),
            top_k=int(cfg.get("top_k", 12)),
        ),
    )
    cache["retriever"] = retriever
    return retriever


def run(state: AgentState) -> AgentState:
    cfg = state["config"]["retrieval"]
    repo_path = state["repo_path"]
    issue = state["issue"]
    step("retriever", "hybrid BM25 + dense + graph")

    retriever = _build_retriever(repo_path, cfg)
    query = f"{issue.get('title','')}\n\n{issue.get('body','')[:3000]}"
    chunks = retriever.query(query)
    info(f"retrieved {len(chunks)} chunks")
    state["retrieved"] = chunks

    # Convention learner: best-effort, runs once per repo per process.
    cache = mapper_node.cached(repo_path)
    if "conventions" not in cache:
        try:
            llm = get_llm(state["config"])
            cache["conventions"] = learn_conventions(
                issue["repo"], llm, n=int(state["config"].get("github", {}).get("scrape_recent_prs", 15))
            )
        except Exception as e:                                          # noqa: BLE001
            cache["conventions"] = f"(convention learner skipped: {e})"
    state["conventions"] = cache["conventions"]

    trace(
        state,
        "retriever",
        top=[{"qn": c.qualified_name, "file": c.file, "score": round(c.score, 3),
              "sources": c.sources} for c in chunks[:6]],
    )
    return state
