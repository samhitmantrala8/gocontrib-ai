"""Wraps the Go toolchain. Every check is best-effort — when ``go`` isn't on
PATH we return a sentinel so the validator can mark ``no_toolchain`` instead
of crashing. This lets the agent be useful for review even on machines that
don't have Go installed."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class ToolResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    skipped: bool = False           # True when the tool isn't available


def _go_bin(go_binary: str = "go") -> Optional[str]:
    return shutil.which(go_binary)


def _run(cmd: list[str], cwd: str, timeout: int) -> ToolResult:
    try:
        res = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as e:
        return ToolResult(False, stderr=f"timeout after {timeout}s: {e}")
    return ToolResult(res.returncode == 0, res.stdout, res.stderr)


def gofmt_check(
    repo_path: str,
    go_binary: str = "go",
    *,
    files: Optional[list[str]] = None,
) -> ToolResult:
    """Run ``gofmt -l`` on either the whole tree (``files=None``) or the
    specific files we just touched. The latter avoids flagging unrelated
    upstream files that happen to be unformatted in the repo."""
    if not _go_bin(go_binary):
        return ToolResult(True, skipped=True)
    if files is not None:
        files = [f for f in files if f.endswith(".go")]
        if not files:
            return ToolResult(True)
        res = _run(["gofmt", "-l", *files], repo_path, 30)
    else:
        res = _run(["gofmt", "-l", "."], repo_path, 30)
    if not res.ok:
        return res
    return ToolResult(ok=(res.stdout.strip() == ""), stdout=res.stdout, stderr=res.stderr)


def go_vet(repo_path: str, go_binary: str = "go", pkg: str = "./...") -> ToolResult:
    if not _go_bin(go_binary):
        return ToolResult(True, skipped=True)
    return _run([go_binary, "vet", pkg], repo_path, 90)


def go_build(repo_path: str, go_binary: str = "go", pkg: str = "./...") -> ToolResult:
    if not _go_bin(go_binary):
        return ToolResult(True, skipped=True)
    return _run([go_binary, "build", pkg], repo_path, 180)


def go_test(
    repo_path: str,
    *,
    go_binary: str = "go",
    pkg: str = "./...",
    run_filter: Optional[str] = None,
    timeout: int = 120,
) -> ToolResult:
    if not _go_bin(go_binary):
        return ToolResult(True, skipped=True)
    cmd = [go_binary, "test", "-count=1", "-timeout", f"{timeout}s"]
    if run_filter:
        cmd += ["-run", run_filter]
    cmd.append(pkg)
    return _run(cmd, repo_path, timeout + 15)


def go_available(go_binary: str = "go") -> bool:
    return _go_bin(go_binary) is not None
