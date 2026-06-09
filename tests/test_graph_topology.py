"""Smoke-test the graph wiring without running real agents.

We patch every node to a no-op that flips the obvious decision flags. This
proves the conditional edges route the way the README diagram claims.
"""

import importlib

import pytest


@pytest.fixture
def patched_graph(monkeypatch):
    # Patch every agent's `run` to a deterministic stub before importing graph.
    from go_contributor.agents import (
        critic, mapper, patcher, planner, pr_writer, reproducer, retriever, triage,
    )
    from go_contributor.state import CriticVerdict, Plan

    def stub_triage(state):
        state["in_scope"] = True
        state["issue_kind"] = "bug"
        return state

    def stub_mapper(state):
        state["repo_path"] = "/tmp/fake"
        state["repo_indexed"] = True
        return state

    def stub_retriever(state):
        state["retrieved"] = []
        state["conventions"] = ""
        return state

    def stub_planner(state):
        state["plan"] = Plan(summary="x", hypothesis="y", target_files=[],
                             target_symbols=[], edits=[], test_strategy="")
        return state

    def stub_reproducer(state):
        return state

    def stub_patcher(state):
        state["diff"] = "diff --git a/a b/a\n--- a/a\n+++ b/a\n+x\n"
        state["files_touched"] = ["a.go"]
        return state

    def stub_critic(state):
        state["critic"] = CriticVerdict(decision="ship", rationale="ok")
        return state

    def stub_pr_writer(state):
        state["pr_title"] = "T"
        state["pr_body"] = "Fixes #1\n\nB"
        return state

    monkeypatch.setattr(triage, "run", stub_triage)
    monkeypatch.setattr(mapper, "run", stub_mapper)
    monkeypatch.setattr(retriever, "run", stub_retriever)
    monkeypatch.setattr(planner, "run", stub_planner)
    monkeypatch.setattr(reproducer, "run", stub_reproducer)
    monkeypatch.setattr(patcher, "run", stub_patcher)
    monkeypatch.setattr(critic, "run", stub_critic)
    monkeypatch.setattr(pr_writer, "run", stub_pr_writer)

    # Re-import graph so the stubs are bound.
    import go_contributor.graph as graph_mod
    importlib.reload(graph_mod)
    return graph_mod.build_graph()


def test_happy_path_runs_to_pr_writer(patched_graph):
    state = {
        "issue": {"repo": "x/y", "number": 1, "title": "t", "body": "b", "labels": []},
        "config": {"patcher": {"max_revise_loops": 3}, "guardrails": {}},
        "trace": [],
    }
    final = patched_graph.invoke(state, config={"recursion_limit": 30})
    assert final["pr_title"] == "T"
    assert "Fixes #1" in final["pr_body"]
