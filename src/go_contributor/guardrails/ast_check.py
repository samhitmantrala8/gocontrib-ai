"""AST-must-parse guardrail. Any patched .go file is re-parsed with
tree-sitter; if the result has any ``ERROR`` nodes the patch is rejected
*before* it gets to the slow ``go build`` validator. Catches the long tail
of "LLM dropped a brace" failures cheaply."""

from __future__ import annotations

from pathlib import Path

from ..tools import ast_go


def check_files(repo_path: str, files: list[str]) -> list[str]:
    out: list[str] = []
    for rel in files:
        if not rel.endswith(".go"):
            continue
        p = Path(repo_path) / rel
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if not ast_go.parse_ok(text):
            out.append(f"{rel}: failed to parse after patch")
    return out
