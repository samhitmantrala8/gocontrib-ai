# GoContrib-AI

An agentic platform that picks up a GitHub issue from one of `gin-gonic/gin`,
`spf13/cobra`, `go-playground/validator`, or `golangci/golangci-lint`,
inspects the repo, plans a fix, edits the code, validates with the Go
toolchain, and produces a patch plus a PR title and body. Runs locally, no
hosted services required.

It is built on LangGraph, with a ReAct-style patcher loop, a Reflexion-style
critic, hybrid RAG over the Go AST, and a guardrail layer that refuses
unsafe or out-of-scope edits.

## Why this is more than a wrapper around an LLM

Most "AI coding agents" are a single prompt around `git diff`. This one is
a graph of small specialised agents, each with a narrow contract, a typed
state schema, and a documented failure mode. Things worth flagging:

1. Tree-sitter Go AST retrieval. Chunks are full symbols (functions,
   methods, types), not arbitrary token windows. Every retrieved chunk is a
   compilable unit with its qualified name and line range attached.
2. Hybrid retriever. BM25 for exact identifier hits, MiniLM dense
   embeddings for paraphrased intent, and a one-hop call-graph expansion
   for the symbol the patcher will need next. Stage weights are tunable in
   `config.yaml`.
3. Reproducer node. Before editing, the system tries to synthesise a
   failing Go test that exercises the bug. If the test passes on the first
   run, the planner hypothesis was probably wrong, and the critic sees
   that on the next loop.
4. Reflexion critic. The patcher and validator feed into a critic that
   returns ship, revise, or abort. On revise, its rationale and
   suggestions go back to the patcher as feedback.
5. Three layers of guardrails. Pre-write policy (banned paths, banned
   patterns) runs in milliseconds. AST-must-parse runs after the patcher
   finishes. The Go toolchain runs last. The slowest check happens only
   when the cheaper checks pass.
6. Convention learner. On first contact with a repo, it pulls the last N
   merged PRs and asks the LLM for a 200-word style sheet. Future runs
   condition the patcher and PR writer on this.

The full design rationale and stack trade-offs are in
[`docs/APPROACH.md`](docs/APPROACH.md).

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

cp .env.example .env
# Edit .env: set GEMINI_API_KEYS (comma-separated, free tier from
# https://aistudio.google.com/apikey). OPENROUTER_API_KEYS optional, used
# as fallback when the whole Gemini pool rate-limits.

python -m go_contributor run \
  --repo go-playground/validator \
  --issue 1517 \
  --workdir ./workspace
```

Outputs land in `workspace/output/`:

```
patch.diff      unified diff against HEAD
pr.md           PR title and body
trace.json      full agent trace, every node, every tool call
```

For a dry run with no real GitHub fetch, an offline fixture is included:

```bash
python -m go_contributor run --fixture examples/gin_3936
```

## Architecture at a glance

```
  Step  Node          Reads from state            Writes to state
  ----  ------------  --------------------------  ------------------------------
  1     triage        issue                       in_scope, issue_kind
  2     mapper        issue                       repo_path, repo_indexed
  3     retriever     issue, repo_path            retrieved, conventions
  4     planner       issue, retrieved            plan
  5     reproducer    plan, repo_path             repro_test_path, repro_failed
  6     patcher       plan, retrieved, feedback   diff, files_touched
  7     guardrails    diff, files_touched         guardrail_violations
  8     validator     repo_path, files_touched    validation
  9     critic        diff, validation, plan      critic verdict
 10     pr_writer     diff, plan, validation      pr_title, pr_body

  Routing edges:
      triage:   in_scope=False                 ->   abort
      triage:   in_scope=True                  ->   mapper
      critic:   verdict=ship                   ->   pr_writer
      critic:   verdict=revise && loops<cap    ->   patcher (with feedback)
      critic:   verdict=abort                  ->   abort
```

State flows as a typed `AgentState` (see `src/go_contributor/state.py`).
LangGraph handles the conditional edges, retry budget, and checkpointing.

## Configuration

Everything user-tunable lives in `config.yaml`:

```yaml
llm:
  provider: gemini
  model: gemini-2.5-flash-lite
  fallback_provider: openrouter
  fallback_model: deepseek/deepseek-chat
retrieval:
  bm25_weight: 0.4
  dense_weight: 0.5
  graph_weight: 0.1
  top_k: 12
patcher:
  max_react_steps: 18
  max_revise_loops: 3
guardrails:
  max_diff_lines: 400
  banned_paths: ["vendor/", "*.pem", "Dockerfile", ".github/workflows/"]
```

The runtime accepts comma-separated `GEMINI_API_KEYS` and
`OPENROUTER_API_KEYS`. It rotates across every (key, model) pair in turn,
falling through to OpenRouter only after the whole Gemini pool returns 429.

## Project layout

```
src/go_contributor/
  __main__.py            CLI entry point
  graph.py               LangGraph state machine
  state.py               typed state schema
  llm.py                 multi-key, multi-model client with rotation
  agents/
    triage.py            classify and scope the issue
    mapper.py            clone repo, build AST index
    retriever.py         hybrid BM25 plus dense plus graph
    planner.py           structured JSON plan
    reproducer.py        synth a failing Go test first
    patcher.py           ReAct loop with six tools
    critic.py            Reflexion: ship, revise, abort
    pr_writer.py         PR title and body
  tools/
    fs.py                path-safe file system
    grep.py              ripgrep-style search
    ast_go.py            tree-sitter-go: symbols and call graph
    git_ops.py           branch, diff, apply
    go_toolchain.py      gofmt, vet, build, focused test
    github_api.py        issue fetch, recent merged PR scrape
  rag/
    indexer.py           AST-aware chunker
    bm25.py              rank-bm25 wrapper with Go-aware tokenizer
    dense.py             sentence-transformers + ChromaDB
    hybrid.py            weighted fusion
    convention_learner.py
  guardrails/
    policy.py            path, size, pattern bans
    ast_check.py         patched files must parse
    validator.py         go vet, build, focused tests
prompts/                 standalone .md files, one per agent
docs/APPROACH.md         long-form rationale
examples/                replayable issue fixtures
tests/                   pytest unit tests
```

## Tests

```bash
pytest -q
python -m go_contributor run --fixture examples/gin_3936
```

## Limits worth knowing

* Scope. Small or medium issues only. Architectural changes are explicitly
  rejected by the triage agent.
* Cost. Free on Gemini's free tier for one issue. Local embeddings and BM25
  mean retrieval is free. OpenRouter is paid (cheap) and only kicks in when
  the Gemini pool rate-limits.
* Determinism. Temperature 0.1 plus a fixed retrieval seed gets you stable
  outputs across runs, but the ReAct loop is not bit-identical.
* Go toolchain required. The validator runs the real Go compiler. Without
  it, the validator emits one warning and the critic decides on the diff
  alone.
