"""Triage: decide whether the issue is in scope, classify it, and pull out
candidate identifiers / files mentioned in the issue body."""

from __future__ import annotations

from ..state import AgentState
from ..utils.logging import step
from ._common import get_llm, load_prompt, trace


def run(state: AgentState) -> AgentState:
    issue = state["issue"]
    step("triage", f"classifying issue {issue['repo']}#{issue['number']}: {issue.get('title','')[:80]}")
    llm = get_llm(state["config"])
    user = (
        f"Repository: {issue['repo']}\n"
        f"Title: {issue.get('title','')}\n"
        f"Labels: {', '.join(issue.get('labels', []))}\n\n"
        f"Body:\n{issue.get('body','')[:6000]}"
    )
    try:
        data = llm.complete_json(load_prompt("triage"), user)
    except Exception as e:                                              # noqa: BLE001
        # Fail-open: if the LLM is unreachable we proceed but mark in_scope
        # by a heuristic. Better to attempt than to abort silently.
        state["in_scope"] = True
        state["scope_reason"] = f"triage llm failed: {e}; defaulted in_scope"
        state["issue_kind"] = "bug"
        trace(state, "triage", error=str(e))
        return state

    state["in_scope"] = bool(data.get("in_scope", False))
    state["scope_reason"] = str(data.get("reason", ""))
    state["issue_kind"] = str(data.get("kind", "bug"))
    trace(
        state,
        "triage",
        in_scope=state["in_scope"],
        kind=state["issue_kind"],
        reason=state["scope_reason"][:200],
    )
    return state
