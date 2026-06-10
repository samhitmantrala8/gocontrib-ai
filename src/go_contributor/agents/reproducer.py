"""Reproducer: try to synthesise a Go test that fails *because of the bug*.

This is the cheap version of "bug-driven development":
1. Ask the LLM to write a focused ``TestIssueNNNN_Reproduce`` Go test that
   exercises the symbols the planner flagged.
2. Drop it into a new ``_test.go`` next to one of the target files.
3. Run ``go test`` for that package only. Expected outcome: FAIL.
4. If it FAILS as expected → ``repro_failed_as_expected = True``.
   The patcher knows it has a real, runnable target. After the patch, the
   validator will re-run this test and it must PASS.
5. If it PASSES on first run, the bug isn't where the planner thinks. We
   keep the test (it's a nice regression check) but record the surprise so
   the planner can revise on the next critic loop.
6. If ``go`` isn't available, we skip cleanly.

This whole node is enabled by ``patcher.reproducer_enabled`` in config.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..state import AgentState
from ..tools import go_toolchain
from ..utils.logging import info, step, warn
from ._common import get_llm, load_prompt, trace


def _pick_dir(state: AgentState) -> str | None:
    plan = state.get("plan")
    if not plan or not plan.target_files:
        return None
    for f in plan.target_files:
        d = os.path.dirname(f)
        if d and (Path(state["repo_path"]) / d).is_dir():
            return d
    return ""


def run(state: AgentState) -> AgentState:
    if not state["config"]["patcher"].get("reproducer_enabled", True):
        trace(state, "reproducer", skipped="disabled-in-config")
        return state
    if not go_toolchain.go_available(state["config"]["validator"].get("go_binary", "go")):
        trace(state, "reproducer", skipped="no-go-toolchain")
        return state

    plan = state.get("plan")
    if plan is None:
        trace(state, "reproducer", skipped="no-plan")
        return state

    step("reproducer", "synthesising failing test")
    target_dir = _pick_dir(state)
    if target_dir is None:
        warn("no plan target dir; skipping reproducer")
        trace(state, "reproducer", skipped="no-target-dir")
        return state

    issue = state["issue"]
    user = (
        f"## Issue {issue['repo']}#{issue['number']}\n"
        f"{issue.get('title','')}\n\n{issue.get('body','')[:3000]}\n\n"
        f"## Plan summary\n{plan.summary}\n## Target symbols\n{', '.join(plan.target_symbols)}\n"
        f"## Target package directory\n{target_dir or '(repo root)'}\n"
    )
    llm = get_llm(state["config"])
    raw = llm.complete(load_prompt("reproducer"), user)

    code = _extract_go_block(raw)
    if not code:
        warn("reproducer LLM returned no code; skipping")
        trace(state, "reproducer", skipped="no-code")
        return state

    test_path = os.path.join(target_dir, f"issue_{issue['number']}_repro_test.go")
    full = Path(state["repo_path"]) / test_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(code, encoding="utf-8")

    pkg = f"./{target_dir}/..." if target_dir else "./..."
    res = go_toolchain.go_test(state["repo_path"], pkg=pkg, run_filter="Reproduce", timeout=60)
    state["repro_test_path"] = test_path

    if res.skipped:
        trace(state, "reproducer", skipped="toolchain-disappeared")
        return state

    if not res.ok:
        info("repro test failed (as expected). bug confirmed runnable")
        state["repro_failed_as_expected"] = True
    else:
        warn("repro test PASSED unexpectedly: planner hypothesis may be wrong")
        state["repro_failed_as_expected"] = False
    trace(
        state,
        "reproducer",
        path=test_path,
        failed_as_expected=bool(state.get("repro_failed_as_expected")),
    )
    return state


_GO_FENCE = re.compile(r"```go\s*(.+?)```", re.DOTALL)


def _extract_go_block(raw: str) -> str | None:
    m = _GO_FENCE.search(raw)
    if m:
        return m.group(1).strip() + "\n"
    if raw.strip().startswith("package "):
        return raw.strip() + "\n"
    return None
