"""Scrapes the recent merged PRs of a repo and asks the LLM to distil a short
conventions document. The patcher is conditioned on this so the diffs match
the project's house style (commit verbs, error wrapping, test naming).

We keep the output deliberately short (~10 bullets). Long convention prompts
mostly get ignored by the LLM during a tool loop."""

from __future__ import annotations

from pathlib import Path

from ..llm import LLM
from ..tools import github_api


_SYSTEM = """You are reviewing recent merged pull requests for a Go open-source project.
Distil at most 10 short bullets that capture the project's contribution conventions:
commit/PR title style, test naming, error-wrapping idioms, doc-comment style,
how breaking changes are flagged, and any policy that appears repeatedly.

Write each bullet as a directive ("Use foo, not bar"). Keep total under 200 words.
If the sample is too small to be confident, say so on the first line."""


def learn(repo: str, llm: LLM, *, n: int = 15, cache_dir: str | None = None) -> str:
    cache_path = None
    if cache_dir:
        cache_path = Path(cache_dir) / f"conventions_{repo.replace('/', '_')}.md"
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")

    prs = github_api.list_recent_merged_prs(repo, n=n)
    if not prs:
        result = (
            "Conventions could not be auto-learned (no PRs fetched). "
            "Defaulting to: short imperative commit titles, table-driven tests, "
            "error wrapping with fmt.Errorf(\"%w\")."
        )
    else:
        sample = "\n\n".join(
            f"PR #{p['number']}: {p['title']}\n{p['body'][:800]}" for p in prs
        )
        try:
            result = llm.complete(_SYSTEM, sample).strip()
        except Exception as e:                                          # noqa: BLE001
            result = f"(convention learner failed: {e}) Defaulting to standard Go style."

    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(result, encoding="utf-8")
    return result
