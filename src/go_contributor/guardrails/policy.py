"""Pre-write policy checks. These are *cheap* and run before every patcher
write, so a runaway agent can't, say, overwrite ``go.mod`` or stamp the
worktree with binaries."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Iterable


@dataclass
class PolicyConfig:
    max_diff_lines: int = 400
    max_files_touched: int = 8
    banned_paths: list[str] = None              # type: ignore[assignment]
    banned_patterns: list[str] = None           # type: ignore[assignment]
    forbid_new_dependencies: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "PolicyConfig":
        return cls(
            max_diff_lines=int(d.get("max_diff_lines", 400)),
            max_files_touched=int(d.get("max_files_touched", 8)),
            banned_paths=list(d.get("banned_paths", []) or []),
            banned_patterns=list(d.get("banned_patterns", []) or []),
            forbid_new_dependencies=bool(d.get("forbid_new_dependencies", True)),
        )


def is_banned_path(path: str, banned: Iterable[str]) -> bool:
    for pat in banned:
        if pat.endswith("/") and (path.startswith(pat) or f"/{pat}" in path):
            return True
        if fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(path, f"*/{pat}"):
            return True
    return False


def check_write(path: str, new_content: str, cfg: PolicyConfig) -> list[str]:
    """Returns a list of violations. Empty list = ok."""
    out: list[str] = []
    if is_banned_path(path, cfg.banned_paths or []):
        out.append(f"path {path!r} is in the banned list")
    if cfg.forbid_new_dependencies and path == "go.mod":
        out.append("modifying go.mod is forbidden by config (forbid_new_dependencies)")
    for pat in cfg.banned_patterns or []:
        if pat in new_content:
            out.append(f"new content contains banned pattern {pat!r}")
    return out


def check_diff(diff_text: str, files_touched: list[str], cfg: PolicyConfig) -> list[str]:
    """Post-patch policy checks: total size + file count."""
    out: list[str] = []
    if len(files_touched) > cfg.max_files_touched:
        out.append(
            f"{len(files_touched)} files touched (cap is {cfg.max_files_touched})"
        )
    diff_lines = sum(
        1 for l in diff_text.splitlines() if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))
    )
    if diff_lines > cfg.max_diff_lines:
        out.append(
            f"diff has {diff_lines} changed lines (cap is {cfg.max_diff_lines})"
        )
    for f in files_touched:
        if is_banned_path(f, cfg.banned_paths or []):
            out.append(f"banned path touched in diff: {f}")
    return out
