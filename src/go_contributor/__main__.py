"""CLI entry point.

Usage:
    python -m go_contributor run --repo gin-gonic/gin --issue 3936
    python -m go_contributor run --fixture examples/gin_3936
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer
import yaml
from dotenv import load_dotenv
from rich.console import Console

from .graph import build_graph
from .state import AgentState
from .tools import github_api
from .utils.logging import console as log_console, err, info, step


app = typer.Typer(add_completion=False, help="GoContrib-AI: agentic AI contributor for Go OSS.")


def _load_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        # Walk up the parent chain so this works when run from a sub-directory.
        for parent in Path.cwd().parents:
            if (parent / "config.yaml").exists():
                p = parent / "config.yaml"
                break
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@app.command("run")
def run_cmd(
    repo: Optional[str] = typer.Option(None, help="GitHub repo, e.g. gin-gonic/gin"),
    issue: Optional[int] = typer.Option(None, help="Issue number"),
    fixture: Optional[str] = typer.Option(None, help="Path to a fixture directory"),
    workdir: str = typer.Option("workspace", help="Where to clone repos / write outputs"),
    config_path: str = typer.Option("config.yaml", "--config"),
):
    """Run the agent on a GitHub issue (or a local fixture)."""
    load_dotenv()
    cfg = _load_config(config_path)
    out_dir = workdir
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    issue_ctx: dict
    if fixture:
        issue_ctx = _load_fixture(fixture)
    else:
        if not repo or not issue:
            err("Provide either --fixture, or both --repo and --issue.")
            raise typer.Exit(2)
        step("cli", f"fetching issue {repo}#{issue} from GitHub")
        info_obj = github_api.fetch_issue(repo, issue)
        issue_ctx = {
            "repo": info_obj.repo,
            "number": info_obj.number,
            "title": info_obj.title,
            "body": info_obj.body,
            "labels": info_obj.labels,
            "url": info_obj.url,
        }

    state: AgentState = {
        "issue": issue_ctx,
        "config": cfg,
        "output_dir": out_dir,
        "trace": [],
    }
    graph = build_graph()
    final = graph.invoke(state, config={"recursion_limit": 50})

    if final.get("error"):
        err(f"agent ended with: {final['error']}")
        # We still write whatever trace we have.
        out = Path(out_dir) / "output"
        out.mkdir(parents=True, exist_ok=True)
        (out / "trace.json").write_text(
            json.dumps(final.get("trace", []), indent=2, default=str), encoding="utf-8"
        )
        raise typer.Exit(1)

    log_console.rule("[green]done[/green]")
    info(f"PR title: {final.get('pr_title','')}")
    info(f"diff size: {len((final.get('diff') or '').splitlines())} lines")
    info(f"output dir: {Path(out_dir).resolve() / 'output'}")


@app.command("describe")
def describe():
    """Print the agent graph topology, then exit."""
    print(
        "graph:\n"
        "  triage → mapper → retriever → planner → reproducer → patcher → critic\n"
        "  critic => ship→pr_writer | revise→patcher | abort→END\n"
    )


def _load_fixture(path: str) -> dict:
    fp = Path(path)
    issue_path = fp / "issue.json"
    if not issue_path.exists():
        raise FileNotFoundError(f"fixture missing issue.json at {issue_path}")
    with issue_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
