"""Path-safe filesystem tools. Every tool is sandboxed to ``repo_path``;
attempts to escape via ``..`` raise ``PathOutsideRepoError`` rather than
silently reading the host filesystem."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


class PathOutsideRepoError(ValueError):
    pass


def _resolve(repo_path: str, rel: str) -> Path:
    root = Path(repo_path).resolve()
    target = (root / rel).resolve()
    if not str(target).startswith(str(root)):
        raise PathOutsideRepoError(f"{rel!r} escapes repo root")
    return target


def read_file(repo_path: str, rel: str, max_bytes: int = 200_000) -> str:
    p = _resolve(repo_path, rel)
    if not p.exists():
        raise FileNotFoundError(rel)
    data = p.read_bytes()[:max_bytes]
    return data.decode("utf-8", errors="replace")


def write_file(repo_path: str, rel: str, content: str) -> None:
    p = _resolve(repo_path, rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def list_dir(repo_path: str, rel: str = ".", max_entries: int = 200) -> list[str]:
    p = _resolve(repo_path, rel)
    if not p.exists() or not p.is_dir():
        return []
    out: list[str] = []
    for entry in sorted(p.iterdir()):
        if entry.name.startswith(".git"):
            continue
        suffix = "/" if entry.is_dir() else ""
        out.append(f"{entry.name}{suffix}")
        if len(out) >= max_entries:
            out.append("...")
            break
    return out


def walk_go_files(repo_path: str, *, exclude: Iterable[str] = ("vendor", ".git", "testdata")) -> list[str]:
    root = Path(repo_path).resolve()
    skip = {s for s in exclude}
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
        for f in filenames:
            if f.endswith(".go"):
                rel = os.path.relpath(os.path.join(dirpath, f), root)
                out.append(rel)
    out.sort()
    return out
