"""Git operations. Wraps GitPython where it's nice and shells out where it isn't.

The agent works on a fresh branch so the user's main is never touched."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Optional

from git import Repo


def clone_or_open(remote_url: str, dest: str, branch: Optional[str] = None) -> Repo:
    p = Path(dest)
    if p.exists() and (p / ".git").exists():
        repo = Repo(dest)
        try:
            repo.remotes.origin.fetch()
        except Exception:                                               # noqa: BLE001
            pass
        return repo
    p.parent.mkdir(parents=True, exist_ok=True)
    return Repo.clone_from(remote_url, dest, depth=1, branch=branch)


def checkout_new_branch(repo: Repo, prefix: str, issue_number: int) -> str:
    name = f"{prefix}issue-{issue_number}-{int(time.time())}"
    repo.git.checkout("-b", name)
    return name


def diff_vs_head(repo_path: str) -> str:
    res = subprocess.run(
        ["git", "diff", "--no-color", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return res.stdout


def files_touched(repo_path: str) -> list[str]:
    res = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return [l for l in res.stdout.splitlines() if l.strip()]


def reset_hard(repo_path: str) -> None:
    subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=repo_path, check=False)
    subprocess.run(["git", "clean", "-fd"], cwd=repo_path, check=False)
