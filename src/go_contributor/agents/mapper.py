"""Mapper: clone the repo (idempotent), checkout a fresh agent branch, build
the AST symbol index. Output is held in module-level state so the retriever
node can reuse the parsed symbols without re-walking the disk."""

from __future__ import annotations

from pathlib import Path

from ..rag.indexer import build_chunks, build_symbol_graph
from ..state import AgentState
from ..tools import git_ops, github_api
from ..utils.logging import info, step
from ._common import trace


# Module-level cache so retriever / patcher don't re-index.
_CACHE: dict[str, dict] = {}


def cached(repo_path: str) -> dict:
    return _CACHE.setdefault(repo_path, {})


def clear_cache() -> None:
    _CACHE.clear()


def run(state: AgentState) -> AgentState:
    issue = state["issue"]
    workdir = state.get("output_dir") or "workspace"
    repo_dir = str(Path(workdir) / issue["repo"].split("/")[-1])
    Path(workdir).mkdir(parents=True, exist_ok=True)

    step("mapper", f"clone+index {issue['repo']} → {repo_dir}")
    repo = git_ops.clone_or_open(github_api.repo_clone_url(issue["repo"]), repo_dir)
    branch_prefix = state["config"].get("github", {}).get("default_branch_prefix", "gocontrib-ai/")
    branch = git_ops.checkout_new_branch(repo, branch_prefix, issue["number"])
    info(f"branch: {branch}")

    chunks = build_chunks(
        repo_dir,
        max_chars=int(state["config"]["retrieval"].get("max_chunk_chars", 4000)),
    )
    graph = build_symbol_graph(repo_dir)
    info(f"indexed {len(chunks)} symbols across {len({c.file for c in chunks})} files")

    cached(repo_dir).update({"chunks": chunks, "graph": graph, "branch": branch})

    state["repo_path"] = repo_dir
    state["repo_indexed"] = True
    state["file_count"] = len({c.file for c in chunks})
    state["symbol_count"] = len(chunks)
    trace(state, "mapper", repo_path=repo_dir, branch=branch, symbols=len(chunks))
    return state
