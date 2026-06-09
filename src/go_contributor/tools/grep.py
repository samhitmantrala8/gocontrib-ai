"""ripgrep-style search. Uses the system ``rg`` if available (fast on large
repos like cobra/gin), else falls back to a pure-Python scan over .go files."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .fs import walk_go_files


def grep(
    repo_path: str,
    pattern: str,
    *,
    file_glob: Optional[str] = None,
    max_hits: int = 80,
) -> list[dict]:
    if shutil.which("rg"):
        return _rg(repo_path, pattern, file_glob, max_hits)
    return _py_grep(repo_path, pattern, file_glob, max_hits)


def _rg(repo_path: str, pattern: str, glob: Optional[str], max_hits: int) -> list[dict]:
    cmd = ["rg", "--no-heading", "-n", "--color=never", pattern]
    if glob:
        cmd += ["-g", glob]
    cmd += ["--max-count", str(max_hits)]
    try:
        res = subprocess.run(
            cmd, cwd=repo_path, capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        return []
    out: list[dict] = []
    for line in res.stdout.splitlines()[:max_hits]:
        # Format: <file>:<line>:<text>
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        out.append({"file": parts[0], "line": int(parts[1]), "text": parts[2]})
    return out


def _py_grep(repo_path: str, pattern: str, glob: Optional[str], max_hits: int) -> list[dict]:
    rx = re.compile(pattern)
    files = walk_go_files(repo_path)
    if glob and not glob.startswith("*.go"):
        # Fall back to including all files when a non-go glob is requested.
        from pathlib import PurePath
        files = [
            str(p.relative_to(repo_path))
            for p in Path(repo_path).rglob("*")
            if p.is_file() and PurePath(p.name).match(glob)
        ]
    out: list[dict] = []
    for rel in files:
        try:
            text = (Path(repo_path) / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                out.append({"file": rel, "line": i, "text": line[:300]})
                if len(out) >= max_hits:
                    return out
    return out
