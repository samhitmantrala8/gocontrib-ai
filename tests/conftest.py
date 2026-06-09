"""Shared pytest fixtures: a tiny synthetic Go repo we can index and edit
without cloning anything from the network."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def tiny_go_repo(tmp_path: Path) -> str:
    repo = tmp_path / "tinygo"
    repo.mkdir()
    (repo / "go.mod").write_text("module example.com/tiny\n\ngo 1.22\n")
    (repo / "main.go").write_text(
        """package main

import "fmt"

// Greeter prints greetings.
type Greeter struct {
\tName string
}

// Hello returns a greeting.
func (g *Greeter) Hello() string {
\treturn fmt.Sprintf("hello, %s", g.Name)
}

func add(a, b int) int {
\treturn a + b
}

func main() {
\tg := &Greeter{Name: "world"}
\tfmt.Println(g.Hello())
\tfmt.Println(add(1, 2))
}
"""
    )
    (repo / "main_test.go").write_text(
        """package main

import "testing"

func TestAdd(t *testing.T) {
\tif add(1, 2) != 3 {
\t\tt.Fatal("bad")
\t}
}
"""
    )
    # Initialise a minimal git repo so git_ops works.
    if _git_available():
        subprocess.run(["git", "init", "-q"], cwd=repo, check=False)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=False)
        subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=False)
        subprocess.run(["git", "add", "."], cwd=repo, check=False)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=False)
    return str(repo)


def _git_available() -> bool:
    from shutil import which
    return which("git") is not None
