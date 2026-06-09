"""PR writer: produces a title + body in the project's house style. Writes
the patch + PR markdown to ``output_dir``."""

from __future__ import annotations

import json
from pathlib import Path

from ..state import AgentState
from ..utils.logging import info, step
from ._common import get_llm, load_prompt, trace


def run(state: AgentState) -> AgentState:
    step("pr_writer", "drafting PR title + body")
    issue = state["issue"]
    plan = state.get("plan")
    val = state.get("validation")
    user = (
        f"## Issue\n{issue['repo']}#{issue['number']} — {issue.get('title','')}\n\n"
        f"## Issue body\n{issue.get('body','')[:2500]}\n\n"
        f"## Plan summary\n{plan.summary if plan else '(none)'}\n\n"
        f"## Files touched\n{state.get('files_touched', [])}\n\n"
        f"## Diff (truncated)\n```diff\n{(state.get('diff') or '')[:4000]}\n```\n\n"
        f"## Validator\n"
        f"  fmt_ok={getattr(val,'fmt_ok',True)} vet_ok={getattr(val,'vet_ok',True)} "
        f"build_ok={getattr(val,'build_ok',True)} tests_ok={getattr(val,'tests_ok',True)}\n\n"
        f"## Project conventions\n{state.get('conventions','')[:1200]}\n"
    )
    llm = get_llm(state["config"])
    data = llm.complete_json(load_prompt("pr_writer"), user)

    title = str(data.get("title", f"Fix #{issue['number']}: {issue.get('title','')}"))
    body = str(data.get("body", ""))
    if f"#{issue['number']}" not in body:
        body = f"Fixes #{issue['number']}\n\n" + body

    state["pr_title"] = title
    state["pr_body"] = body

    out_dir = Path(state.get("output_dir") or "workspace") / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "patch.diff").write_text(state.get("diff", ""), encoding="utf-8")
    (out_dir / "pr.md").write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    (out_dir / "trace.json").write_text(
        json.dumps(state.get("trace", []), indent=2, default=_json_default), encoding="utf-8"
    )
    info(f"wrote {out_dir}/{'{patch.diff, pr.md, trace.json}'}")
    trace(state, "pr_writer", title=title, out_dir=str(out_dir))
    return state


def _json_default(o):
    # Make our dataclasses JSON-serialisable for the trace.
    if hasattr(o, "__dict__"):
        return o.__dict__
    return str(o)
