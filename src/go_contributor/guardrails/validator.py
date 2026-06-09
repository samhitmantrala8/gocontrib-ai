"""Runs the Go toolchain in the patched repo. We try to be focused: when the
plan names target files, we run tests for the packages those files belong to,
and only fall back to ``./...`` if we can't infer a package."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..state import ValidationResult
from ..tools import go_toolchain


def _packages_for(files: Iterable[str]) -> list[str]:
    pkgs: set[str] = set()
    for f in files:
        if not f.endswith(".go"):
            continue
        d = str(Path(f).parent)
        if d in ("", "."):
            pkgs.add("./.")
        else:
            pkgs.add(f"./{d}/...")
    return sorted(pkgs) or ["./..."]


def run(
    repo_path: str,
    *,
    files_touched: list[str],
    go_binary: str = "go",
    test_timeout: int = 120,
    run_tests: bool = True,
) -> ValidationResult:
    if not go_toolchain.go_available(go_binary):
        return ValidationResult(no_toolchain=True, notes=["go binary not found on PATH; skipped"])

    notes: list[str] = []
    fmt = go_toolchain.gofmt_check(repo_path, go_binary, files=files_touched)
    if fmt.skipped:
        notes.append("gofmt skipped")
    elif not fmt.ok:
        notes.append(f"gofmt: needs formatting:\n{fmt.stdout.strip()[:600]}")

    vet = go_toolchain.go_vet(repo_path, go_binary)
    if not vet.ok:
        notes.append(f"go vet failed:\n{(vet.stderr or vet.stdout)[:1200]}")

    build = go_toolchain.go_build(repo_path, go_binary)
    if not build.ok:
        notes.append(f"go build failed:\n{(build.stderr or build.stdout)[:1500]}")

    tests_ok = True
    failed_tests: list[str] = []
    if run_tests:
        for pkg in _packages_for(files_touched):
            res = go_toolchain.go_test(repo_path, go_binary=go_binary, pkg=pkg, timeout=test_timeout)
            if not res.ok:
                tests_ok = False
                # Extract failed test names from "--- FAIL: TestX" lines
                for line in (res.stdout or "").splitlines():
                    if line.strip().startswith("--- FAIL:"):
                        failed_tests.append(line.split(":", 1)[1].strip().split(" ", 1)[0])
                notes.append(f"tests in {pkg} failed:\n{(res.stdout or res.stderr)[:1500]}")

    return ValidationResult(
        fmt_ok=fmt.ok,
        vet_ok=vet.ok,
        build_ok=build.ok,
        tests_ok=tests_ok,
        notes=notes,
        failed_tests=failed_tests,
    )
