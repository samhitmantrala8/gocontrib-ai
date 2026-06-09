"""Planner: emit a structured fix plan as JSON.

We make the planner *separate* from the patcher because:
* a plan is small enough to fit in one LLM call → cheap to retry
* having the plan in state means the critic can compare diff vs intent
* the reproducer reads ``test_strategy`` directly without re-reading the issue
"""

from __future__ import annotations

from ..state import AgentState, Plan
from ..utils.logging import info, step
from ._common import get_llm, load_prompt, trace


def _retrieved_block(state: AgentState) -> str:
    pieces: list[str] = []
    for c in (state.get("retrieved") or [])[:10]:
        pieces.append(
            f"### {c.qualified_name}  ({c.file}:{c.start_line}-{c.end_line})  "
            f"sources={','.join(c.sources)} score={c.score:.2f}\n"
            f"```go\n{c.code[:1800]}\n```"
        )
    return "\n\n".join(pieces) if pieces else "(no context retrieved)"


def run(state: AgentState) -> AgentState:
    step("planner", "drafting structured fix plan")
    issue = state["issue"]
    user = (
        f"# Issue {issue['repo']}#{issue['number']}\n"
        f"## Title\n{issue.get('title','')}\n\n"
        f"## Body\n{issue.get('body','')[:5000]}\n\n"
        f"## Project conventions\n{state.get('conventions','')[:1500]}\n\n"
        f"## Retrieved context\n{_retrieved_block(state)}\n"
    )
    if state.get("revise_loops", 0) > 0 and state.get("revise_feedback"):
        user += f"\n\n## Critic feedback (your previous attempt was rejected)\n{state['revise_feedback']}\n"

    llm = get_llm(state["config"])
    data = llm.complete_json(load_prompt("planner"), user)

    plan = Plan(
        summary=str(data.get("summary", ""))[:2000],
        hypothesis=str(data.get("hypothesis", "")),
        target_files=[str(f) for f in (data.get("target_files") or [])][:10],
        target_symbols=[str(s) for s in (data.get("target_symbols") or [])][:20],
        edits=list(data.get("edits") or [])[:10],
        test_strategy=str(data.get("test_strategy", "")),
        risk=str(data.get("risk", "low")),
    )
    state["plan"] = plan
    info(f"plan: {plan.summary[:120]}")
    info(f"target_files: {plan.target_files}")
    trace(
        state,
        "planner",
        plan={
            "summary": plan.summary,
            "target_files": plan.target_files,
            "target_symbols": plan.target_symbols,
            "risk": plan.risk,
        },
    )
    return state
