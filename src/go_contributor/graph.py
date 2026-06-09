"""LangGraph state machine wiring all agent nodes together.

The graph is intentionally explicit — no hidden conditional logic inside the
nodes themselves. Routing decisions live at the edges, so the topology is the
documentation.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, StateGraph

from .agents import (
    critic as critic_agent,
    mapper as mapper_agent,
    patcher as patcher_agent,
    planner as planner_agent,
    pr_writer as pr_writer_agent,
    reproducer as reproducer_agent,
    retriever as retriever_agent,
    triage as triage_agent,
)
from .state import AgentState


# ---------------------------------------------------------------------------
# Conditional edges
# ---------------------------------------------------------------------------

def _after_triage(state: AgentState) -> Literal["mapper", "abort"]:
    return "mapper" if state.get("in_scope") else "abort"


def _after_reproducer(state: AgentState) -> Literal["patcher"]:
    # We always proceed to the patcher; the reproducer's failure-to-fail is
    # captured in state and consulted by the planner-on-revise.
    return "patcher"


def _after_critic(state: AgentState) -> Literal["pr_writer", "patcher", "abort"]:
    verdict = state.get("critic")
    if verdict is None:
        return "abort"
    if verdict.decision == "ship":
        return "pr_writer"
    if verdict.decision == "revise":
        cap = state["config"]["patcher"]["max_revise_loops"]
        if state.get("revise_loops", 0) >= cap:
            return "abort"
        return "patcher"
    return "abort"


# ---------------------------------------------------------------------------
# Terminal nodes
# ---------------------------------------------------------------------------

def _abort(state: AgentState) -> AgentState:
    if not state.get("error"):
        reason = state.get("scope_reason") or "agent aborted"
        verdict = state.get("critic")
        if verdict is not None:
            reason = verdict.rationale
        state["error"] = reason
    state.setdefault("trace", []).append({"node": "abort", "reason": state["error"]})
    return state


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph():
    g: StateGraph = StateGraph(AgentState)

    g.add_node("triage", triage_agent.run)
    g.add_node("mapper", mapper_agent.run)
    g.add_node("retriever", retriever_agent.run)
    g.add_node("planner", planner_agent.run)
    g.add_node("reproducer", reproducer_agent.run)
    g.add_node("patcher", patcher_agent.run)
    g.add_node("critic", critic_agent.run)
    g.add_node("pr_writer", pr_writer_agent.run)
    g.add_node("abort", _abort)

    g.set_entry_point("triage")

    g.add_conditional_edges(
        "triage", _after_triage, {"mapper": "mapper", "abort": "abort"}
    )
    g.add_edge("mapper", "retriever")
    g.add_edge("retriever", "planner")
    g.add_edge("planner", "reproducer")
    g.add_conditional_edges(
        "reproducer", _after_reproducer, {"patcher": "patcher"}
    )
    g.add_edge("patcher", "critic")
    g.add_conditional_edges(
        "critic",
        _after_critic,
        {"pr_writer": "pr_writer", "patcher": "patcher", "abort": "abort"},
    )
    g.add_edge("pr_writer", END)
    g.add_edge("abort", END)

    return g.compile()
