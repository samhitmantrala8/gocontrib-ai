"""Typed state schema that flows through the LangGraph state machine.

Every agent node receives the full ``AgentState`` and returns a partial dict
which LangGraph merges. Keeping this in one place is what lets the system stay
debuggable as the graph grows, since every node has a written-down contract for what
it reads and what it writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional, TypedDict


class IssueContext(TypedDict, total=False):
    repo: str                       # "gin-gonic/gin"
    number: int                     # issue number
    title: str
    body: str
    labels: list[str]
    url: str


@dataclass
class RetrievedChunk:
    """A symbol-level chunk: a whole function/method/type, not an arbitrary window."""
    file: str
    qualified_name: str             # e.g. "context.Context.Bind"
    kind: str                       # function | method | type | const
    start_line: int
    end_line: int
    code: str
    score: float = 0.0
    sources: list[str] = field(default_factory=list)   # ["bm25","dense","graph"]

    def short(self) -> str:
        return f"{self.file}:{self.start_line}-{self.end_line} {self.qualified_name}"


@dataclass
class Plan:
    """Structured fix plan emitted by the planner."""
    summary: str
    hypothesis: str
    target_files: list[str]
    target_symbols: list[str]
    edits: list[dict[str, Any]]      # [{"file":..., "intent":...}]
    test_strategy: str
    risk: Literal["low", "medium", "high"] = "low"


@dataclass
class ValidationResult:
    fmt_ok: bool = True
    vet_ok: bool = True
    build_ok: bool = True
    tests_ok: bool = True
    notes: list[str] = field(default_factory=list)
    failed_tests: list[str] = field(default_factory=list)
    no_toolchain: bool = False       # True when `go` is not on PATH

    @property
    def overall_ok(self) -> bool:
        if self.no_toolchain:
            return True              # don't block on a missing toolchain
        return self.fmt_ok and self.vet_ok and self.build_ok and self.tests_ok


@dataclass
class CriticVerdict:
    decision: Literal["ship", "revise", "abort"]
    rationale: str
    suggestions: list[str] = field(default_factory=list)


class AgentState(TypedDict, total=False):
    # --- inputs ----------------------------------------------------------------
    issue: IssueContext
    repo_path: str                  # absolute path to the cloned repo
    output_dir: str
    config: dict[str, Any]

    # --- triage ----------------------------------------------------------------
    in_scope: bool
    scope_reason: str
    issue_kind: str                 # bug | docs | feature | test | refactor

    # --- mapper ----------------------------------------------------------------
    repo_indexed: bool
    file_count: int
    symbol_count: int

    # --- retrieval --------------------------------------------------------------
    retrieved: list[RetrievedChunk]
    conventions: str                 # learned style guide for this repo

    # --- plan ------------------------------------------------------------------
    plan: Optional[Plan]

    # --- reproducer ------------------------------------------------------------
    repro_test_path: Optional[str]
    repro_failed_as_expected: bool

    # --- patch -----------------------------------------------------------------
    diff: str                        # unified diff vs HEAD
    files_touched: list[str]
    react_steps: int

    # --- validation ------------------------------------------------------------
    validation: Optional[ValidationResult]
    guardrail_violations: list[str]

    # --- critic / loop control -------------------------------------------------
    critic: Optional[CriticVerdict]
    revise_loops: int
    revise_feedback: str             # passed back to patcher on revise

    # --- output ----------------------------------------------------------------
    pr_title: str
    pr_body: str

    # --- bookkeeping -----------------------------------------------------------
    trace: list[dict[str, Any]]      # every node + every tool call, for postmortem
    error: Optional[str]
