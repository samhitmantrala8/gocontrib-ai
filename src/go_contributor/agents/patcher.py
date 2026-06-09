"""Patcher: a small ReAct loop. The LLM picks tools by emitting JSON actions
of the form ``{"tool": "...", "args": {...}}``. We execute the tool, append
the observation, and re-call the LLM. The loop terminates when the LLM emits
``{"tool": "finish"}``.

We deliberately keep the tool surface tiny — six tools — because (a) the LLM
gets confused by long tool menus and (b) every tool is wrapped by the
``policy`` guardrail before execution.

Tools:
* read_file(path)            — read a file (clamped to 200kB)
* list_dir(path)             — list a directory
* grep(pattern, glob?)       — ripgrep-style search
* find_symbol(name)          — resolve "qualified.Name" to file/lines/code
* write_file(path, content)  — write a whole file (passes ``policy.check_write`` first)
* finish(notes)              — done; loop exits
"""

from __future__ import annotations

import json
from pathlib import Path

from ..guardrails.policy import PolicyConfig, check_write
from ..state import AgentState
from ..tools import fs, git_ops, grep
from ..utils.logging import info, step, warn
from . import mapper as mapper_node
from ._common import get_llm, load_prompt, trace


_MAX_OBS_CHARS = 5000


def _retrieved_block(state: AgentState) -> str:
    pieces: list[str] = []
    for c in (state.get("retrieved") or [])[:6]:
        pieces.append(
            f"### {c.qualified_name}  ({c.file}:{c.start_line}-{c.end_line})\n"
            f"```go\n{c.code[:1500]}\n```"
        )
    return "\n\n".join(pieces) if pieces else "(no context)"


def _system_prompt(state: AgentState) -> str:
    base = load_prompt("patcher")
    plan = state.get("plan")
    extras = ""
    if plan is not None:
        extras += (
            f"\n\n## Active plan\n"
            f"summary: {plan.summary}\n"
            f"hypothesis: {plan.hypothesis}\n"
            f"target_files: {plan.target_files}\n"
            f"target_symbols: {plan.target_symbols}\n"
            f"test_strategy: {plan.test_strategy}\n"
        )
    extras += f"\n\n## Project conventions\n{state.get('conventions','')[:1500]}\n"
    extras += f"\n\n## Pre-loaded context\n{_retrieved_block(state)}\n"
    if state.get("revise_loops", 0) > 0 and state.get("revise_feedback"):
        extras += f"\n\n## Critic feedback (you must address this)\n{state['revise_feedback']}\n"
    return base + extras


def _resolve_symbol(repo_path: str, name: str) -> dict | None:
    cache = mapper_node.cached(repo_path)
    chunks = cache.get("chunks", [])
    # Try exact qualified match first, then fall back to short name.
    for c in chunks:
        if c.qualified_name == name:
            return _chunk_to_dict(c)
    short = name.split(".")[-1]
    for c in chunks:
        if c.qualified_name.endswith(f".{short}") or c.qualified_name == short:
            return _chunk_to_dict(c)
    return None


def _chunk_to_dict(c) -> dict:
    return {
        "file": c.file,
        "qualified_name": c.qualified_name,
        "kind": c.kind,
        "start_line": c.start_line,
        "end_line": c.end_line,
        "code": c.code,
    }


def _exec_tool(state: AgentState, tool: str, args: dict, policy: PolicyConfig) -> dict:
    repo = state["repo_path"]
    try:
        if tool == "read_file":
            text = fs.read_file(repo, args["path"])
            return {"ok": True, "content": text[:_MAX_OBS_CHARS]}
        if tool == "list_dir":
            return {"ok": True, "entries": fs.list_dir(repo, args.get("path", "."))}
        if tool == "grep":
            hits = grep.grep(repo, args["pattern"], file_glob=args.get("glob"), max_hits=40)
            return {"ok": True, "hits": hits[:40]}
        if tool == "find_symbol":
            sym = _resolve_symbol(repo, args["name"])
            return {"ok": sym is not None, "symbol": sym}
        if tool == "write_file":
            path = args["path"]
            content = args["content"]
            violations = check_write(path, content, policy)
            if violations:
                return {"ok": False, "error": f"policy: {'; '.join(violations)}"}
            fs.write_file(repo, path, content)
            return {"ok": True, "wrote": path, "bytes": len(content)}
        if tool == "replace_in_file":
            path = args["path"]
            old = args["old"]
            new = args["new"]
            try:
                current = fs.read_file(repo, path, max_bytes=2_000_000)
            except FileNotFoundError:
                return {"ok": False, "error": f"file not found: {path}"}
            count = current.count(old)
            if count == 0:
                return {"ok": False, "error": "old text not found; read the file again"}
            if count > 1:
                return {"ok": False, "error": f"old text appears {count} times; make it more specific"}
            updated = current.replace(old, new, 1)
            violations = check_write(path, updated, policy)
            if violations:
                return {"ok": False, "error": f"policy: {'; '.join(violations)}"}
            fs.write_file(repo, path, updated)
            return {"ok": True, "wrote": path, "replaced_chars": len(old)}
        if tool == "finish":
            return {"ok": True, "finished": True, "notes": args.get("notes", "")}
        return {"ok": False, "error": f"unknown tool {tool!r}"}
    except Exception as e:                                              # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _parse_action(raw: str) -> dict:
    raw = raw.strip()
    # Strip any code fence wrapping.
    if raw.startswith("```"):
        # remove leading fence + optional language tag
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    start = raw.find("{")
    if start == -1:
        raise ValueError(f"no JSON action in:\n{raw[:300]}")
    # Find the matching close-brace using a depth counter so we ignore
    # any trailing prose / next action the LLM may have appended.
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(raw[start : i + 1])
    raise ValueError(f"unbalanced JSON in:\n{raw[:300]}")


def run(state: AgentState) -> AgentState:
    state["revise_loops"] = state.get("revise_loops", 0) + (1 if state.get("revise_feedback") else 0)
    step("patcher", f"ReAct loop (attempt {state['revise_loops'] + 1})")

    cfg = state["config"]
    max_steps = int(cfg["patcher"].get("max_react_steps", 12))
    policy = PolicyConfig.from_dict(cfg.get("guardrails", {}))

    # On a revise loop we KEEP the previous edits in place so the patcher
    # can refine them based on the critic's feedback. The critic's job was
    # to give actionable guidance; resetting to HEAD throws that away.

    llm = get_llm(cfg)
    sys = _system_prompt(state)
    history: list[dict] = []
    finished = False

    for step_i in range(max_steps):
        # Build the running transcript for the LLM.
        transcript = (
            "Emit ONE JSON action per turn — nothing else. "
            "Return `{\"tool\":\"finish\",\"args\":{\"notes\":\"...\"}}` when the patch is complete.\n\n"
            "## History so far\n"
        )
        if not history:
            transcript += "(empty — pick your first action)\n"
        else:
            for h in history[-8:]:
                transcript += f"\n>>> action: {json.dumps(h['action'])[:600]}\n"
                transcript += f"<<< observation: {json.dumps(h['observation'])[:1200]}\n"
        try:
            raw = llm.complete(sys, transcript)
            action = _parse_action(raw)
        except Exception as e:                                          # noqa: BLE001
            warn(f"step {step_i}: action parse failed: {e}")
            history.append({"action": {"tool": "_error"}, "observation": {"error": str(e)}})
            continue

        tool = str(action.get("tool", ""))
        args = action.get("args", {}) or {}
        info(f"step {step_i}: {tool} {list(args.keys())}")
        observation = _exec_tool(state, tool, args, policy)
        history.append({"action": action, "observation": observation})

        if observation.get("finished"):
            finished = True
            break

    state["react_steps"] = len(history)

    diff = git_ops.diff_vs_head(state["repo_path"])
    state["diff"] = diff
    state["files_touched"] = git_ops.files_touched(state["repo_path"])
    info(f"diff: {len(diff.splitlines())} lines, {len(state['files_touched'])} files touched")

    trace(
        state,
        "patcher",
        finished=finished,
        steps=len(history),
        files_touched=state["files_touched"],
        # keep the trace small: tool names only
        actions=[h["action"].get("tool") for h in history],
    )
    return state
