"""Tiny logging helper. We keep one global rich console so every node prints
in the same style and so it's easy to silence in tests."""

from __future__ import annotations

import os
from rich.console import Console

console = Console(quiet=os.getenv("GOCONTRIB_QUIET") == "1", highlight=False)


def step(node: str, msg: str) -> None:
    console.print(f"[bold cyan]›[/bold cyan] [bold]{node}[/bold] {msg}")


def info(msg: str) -> None:
    console.print(f"  {msg}")


def warn(msg: str) -> None:
    console.print(f"  [yellow]warn[/yellow] {msg}")


def err(msg: str) -> None:
    console.print(f"  [red]error[/red] {msg}")
