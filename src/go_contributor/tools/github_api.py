"""Tiny GitHub client. Uses PyGithub if a token is available, else the public
REST API anonymously (still works for fetching a single issue).

We only need a small surface: fetch one issue, list recent merged PRs."""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Optional


GITHUB_API = "https://api.github.com"


@dataclass
class IssueInfo:
    repo: str
    number: int
    title: str
    body: str
    labels: list[str]
    url: str


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "gocontrib-ai/0.1"}
    tok = os.getenv("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _get(url: str) -> dict | list:
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_issue(repo: str, number: int) -> IssueInfo:
    data = _get(f"{GITHUB_API}/repos/{repo}/issues/{number}")
    return IssueInfo(
        repo=repo,
        number=number,
        title=data.get("title", ""),
        body=data.get("body") or "",
        labels=[l["name"] for l in data.get("labels", []) if isinstance(l, dict)],
        url=data.get("html_url", f"https://github.com/{repo}/issues/{number}"),
    )


def list_recent_merged_prs(repo: str, n: int = 15) -> list[dict]:
    """Return a list of {title, body, number} for the most recent merged PRs."""
    url = f"{GITHUB_API}/repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page={n*2}"
    try:
        data = _get(url)
    except Exception:                                                   # noqa: BLE001
        return []
    out: list[dict] = []
    for pr in data:
        if not isinstance(pr, dict):
            continue
        if pr.get("merged_at"):
            out.append({
                "number": pr["number"],
                "title": pr.get("title", ""),
                "body": (pr.get("body") or "")[:1500],
            })
            if len(out) >= n:
                break
    return out


def repo_clone_url(repo: str) -> str:
    return f"https://github.com/{repo}.git"
