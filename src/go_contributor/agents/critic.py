"""Critic: Reflexion-style judge.

It receives the diff, the validator output, the post-patch guardrail result,
and the plan. It emits one of three decisions:

* ``ship``  — proceed to PR writer
* ``revise`` — bounce back to the patcher with concrete feedback
* ``abort`` — give up; the issue is out of reach for this run

The critic is also where we run the post-patch guardrails (size, paths, AST
must-parse). Putting them here means a single place owns "is this diff
acceptable?" — the patcher is told *what* failed when it's asked to revise.
"""

from __future__ import annotations

from ..guardrails import ast_check
from ..guardrails import validator as validator_node
from ..guardrails.policy import PolicyConfig, check_diff
from ..state import AgentState, CriticVerdict
from ..utils.logging import info, step, warn
from ._common import get_llm, load_prompt, trace


def _short(s: str, n: int = 1500) -> str:
    return s if len(s) <= n else s[:n] + "\n…(truncated)"


def run(state: AgentState) -> AgentState:
    step("critic", "running validators + judging diff")
    cfg = state["config"]
    diff = state.get("diff", "")
    files = state.get("files_touched", [])

    if not diff.strip() or not files:
        state["critic"] = CriticVerdict(
            decision="abort",
            rationale="Patcher produced an empty diff. No code change was attempted.",
        )
        trace(state, "critic", decision="abort", reason="empty-diff")
        return state

    policy = PolicyConfig.from_dict(cfg.get("guardrails", {}))
    policy_violations = check_diff(diff, files, policy)
    parse_violations = ast_check.check_files(state["repo_path"], files)
    state["guardrail_violations"] = policy_violations + parse_violations

    # Validator (gofmt / vet / build / focused tests)
    val_cfg = cfg.get("validator", {})
    val = validator_node.run(
        state["repo_path"],
        files_touched=files,
        go_binary=val_cfg.get("go_binary", "go"),
        test_timeout=int(val_cfg.get("test_timeout_seconds", 120)),
        run_tests=bool(val_cfg.get("run_focused_tests", True)),
    )
    state["validation"] = val

    # Hard fail: AST parse error or banned-path violation → revise immediately,
    # don't waste an LLM call on a clearly-broken patch.
    if parse_violations:
        msg = "Patch produced syntactically invalid Go: " + "; ".join(parse_violations)
        state["critic"] = CriticVerdict(decision="revise", rationale=msg, suggestions=parse_violations)
        state["revise_feedback"] = msg
        trace(state, "critic", decision="revise", reason="ast-fail", details=parse_violations)
        return state
    if any("banned path" in v for v in policy_violations):
        msg = "Patch touched a banned path: " + "; ".join(policy_violations)
        state["critic"] = CriticVerdict(decision="abort", rationale=msg)
        trace(state, "critic", decision="abort", reason="banned-path", details=policy_violations)
        return state

    # If everything looks good and validator is happy, we can short-circuit.
    if not policy_violations and val.overall_ok:
        # Still ask the critic for an opinion — it sometimes catches "wrong fix
        # but compiles" cases. Cheap LLM call, big payoff.
        verdict = _ask_llm_critic(state, val, policy_violations)
        state["critic"] = verdict
        if verdict.decision == "revise":
            state["revise_feedback"] = verdict.rationale + "\n" + "\n".join(verdict.suggestions)
        trace(state, "critic", decision=verdict.decision, rationale=verdict.rationale[:200])
        return state

    # Otherwise tell the LLM critic what's failing and let it decide between revise / abort.
    verdict = _ask_llm_critic(state, val, policy_violations)
    state["critic"] = verdict
    if verdict.decision == "revise":
        state["revise_feedback"] = (
            verdict.rationale
            + "\n\nValidator notes:\n"
            + "\n".join(val.notes[:6])
            + ("\nPolicy:\n" + "\n".join(policy_violations) if policy_violations else "")
        )
    trace(state, "critic", decision=verdict.decision, rationale=verdict.rationale[:200])
    return state


def _ask_llm_critic(state: AgentState, val, policy_violations: list[str]) -> CriticVerdict:
    plan = state.get("plan")
    issue = state["issue"]
    user = (
        f"## Issue {issue['repo']}#{issue['number']}\n{issue.get('title','')}\n\n"
        f"## Plan summary\n{plan.summary if plan else '(none)'}\n"
        f"## Files touched\n{state.get('files_touched', [])}\n\n"
        f"## Diff\n```diff\n{_short(state.get('diff',''), 5000)}\n```\n\n"
        f"## Validator\n"
        f"  fmt_ok={val.fmt_ok} vet_ok={val.vet_ok} build_ok={val.build_ok} "
        f"tests_ok={val.tests_ok} no_toolchain={val.no_toolchain}\n"
        f"  notes:\n{_short(chr(10).join(val.notes), 2500)}\n"
        f"## Policy violations\n{policy_violations or 'none'}\n"
    )
    llm = get_llm(state["config"])
    try:
        data = llm.complete_json(load_prompt("critic"), user)
    except Exception as e:                                              # noqa: BLE001
        warn(f"critic LLM failed, defaulting to abort: {e}")
        return CriticVerdict(decision="abort", rationale=f"critic llm failed: {e}")

    decision = str(data.get("decision", "abort")).lower()
    if decision not in ("ship", "revise", "abort"):
        decision = "abort"
    return CriticVerdict(
        decision=decision,                                              # type: ignore[arg-type]
        rationale=str(data.get("rationale", ""))[:2000],
        suggestions=[str(s) for s in (data.get("suggestions") or [])][:6],
    )
