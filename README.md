# GoContrib-AI

> **An agentic AI contributor for open-source Go projects.**
> Given a GitHub issue from `gin-gonic/gin`, `spf13/cobra`, `go-playground/validator`, or `golangci/golangci-lint`,
> the system inspects the repo, plans a fix, modifies code, validates with the Go toolchain, and produces a
> patch + PR title/body — all locally.

Built around **LangGraph**, a **ReAct** patcher loop, a **Reflexion**-style self-critic, **hybrid RAG** over the Go
AST, and a **guardrail layer** that refuses unsafe or out-of-scope edits.

---

## Why this is not a thin wrapper

Most "AI coding agents" are a single LLM call wrapped around `git diff`. This system is a **graph of specialized
agents**, each with a narrow contract, a typed state schema, and the ability to fail safely back to the
orchestrator. The novel pieces:

1. **Tree-sitter Go AST retrieval** — chunks are *symbols* (functions / methods / types), not arbitrary token
   windows. Retrieval returns whole, compilable units of code with their qualified name, file, and line range.
2. **Hybrid retriever** — BM25 (lexical, great for Go identifier names) ⊕ dense embeddings
   (`sentence-transformers/all-MiniLM-L6-v2`, runs locally on CPU) ⊕ a one-hop symbol-graph expansion. Each
   stage's contribution is tunable via `config.yaml`.
3. **Issue-to-Test reproducer** — before patching, the agent tries to synthesise a failing Go test that
   reproduces the issue. If it fails-to-fail, the patcher knows the bug isn't where it thought and re-plans.
4. **Reflexion-style critic loop** — Patcher ⇄ Validator ⇄ Critic with a bounded retry budget. The critic gets
   diff + validator output + project conventions and decides "ship", "revise", or "abort".
5. **Guardrails layer** — every tool call passes through a policy: max diff size, banned paths
   (`vendor/`, `*.pem`, `Dockerfile`), AST-must-parse, `go vet` must not regress, no new dependencies unless
   asked. Patches that violate any of these are rejected before the critic ever sees them.
6. **Convention learner** — on first run against a repo, the system scrapes the last N merged PRs from the
   GitHub API and distils a `conventions.md` (commit style, test naming, error wrapping). Future runs
   condition the patcher on this file.

Full rationale and stack trade-offs live in [`docs/APPROACH.md`](docs/APPROACH.md).

---

## Quick start

```bash
# 1. Install (Python 3.11+, Go 1.22+ on your PATH)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env: set GEMINI_API_KEY (free tier from https://aistudio.google.com/apikey)
# Optional: GITHUB_TOKEN for higher rate limits, OPENROUTER_API_KEY as Gemini fallback

# 3. Run on an issue
python -m go_contributor run \
  --repo gin-gonic/gin \
  --issue 3936 \
  --workdir ./workspace

# Output:
#   workspace/gin/                <- cloned repo on a fresh branch
#   workspace/output/patch.diff   <- unified diff
#   workspace/output/pr.md        <- PR title + body
#   workspace/output/trace.json   <- full agent trace (every node, every tool call)
```

For a dry run without an LLM key, use the offline fixture:

```bash
python -m go_contributor run --fixture examples/gin_3936
```

---

## Architecture at a glance

```
                       ┌─────────────────────────────┐
   GitHub issue  ─────▶│  Triage Agent (classify,    │
                       │  extract symbols, scope)    │
                       └──────────────┬──────────────┘
                                      ▼
                       ┌─────────────────────────────┐
                       │  Repo Mapper                │
                       │  (clone → AST → index)      │
                       └──────────────┬──────────────┘
                                      ▼
                       ┌─────────────────────────────┐
                       │  Hybrid Retriever           │
                       │  BM25 ⊕ dense ⊕ graph hop   │
                       └──────────────┬──────────────┘
                                      ▼
                       ┌─────────────────────────────┐
                       │  Planner (structured JSON   │
                       │  plan: files, hypotheses,   │
                       │  test strategy)             │
                       └──────────────┬──────────────┘
                                      ▼
                       ┌─────────────────────────────┐
                       │  Reproducer (synth failing  │ ◀──── optional skip
                       │  test; confirm bug is real) │
                       └──────────────┬──────────────┘
                                      ▼
                       ┌─────────────────────────────┐
       ┌──── retry ───▶│  Patcher (ReAct loop with   │
       │               │  read/write/grep/ast tools) │
       │               └──────────────┬──────────────┘
       │                              ▼
       │               ┌─────────────────────────────┐
       │               │  Guardrails (policy + AST)  │
       │               └──────────────┬──────────────┘
       │                              ▼
       │               ┌─────────────────────────────┐
       │               │  Validator (gofmt, vet,     │
       │               │  build, focused tests)      │
       │               └──────────────┬──────────────┘
       │                              ▼
       │               ┌─────────────────────────────┐
       └────── revise ─│  Critic (Reflexion: ship /  │
                       │  revise / abort)            │
                       └──────────────┬──────────────┘
                                      ▼ ship
                       ┌─────────────────────────────┐
                       │  PR Writer                  │
                       └─────────────────────────────┘
```

State flows as a typed `AgentState` (see `src/go_contributor/state.py`). LangGraph handles the conditional
edges, retry budget, and checkpointing.

---

## Configuration

Everything user-tunable lives in `config.yaml`:

```yaml
llm:
  provider: gemini          # gemini | openrouter
  model: gemini-2.0-flash   # cheap + fast for tool loops
  temperature: 0.1
retrieval:
  bm25_weight: 0.4
  dense_weight: 0.5
  graph_weight: 0.1
  top_k: 12
patcher:
  max_react_steps: 12
  max_revise_loops: 3
guardrails:
  max_diff_lines: 400
  banned_paths: ["vendor/", "*.pem", "Dockerfile", ".github/workflows/"]
```

---

## Project layout

```
src/go_contributor/
  __main__.py            # CLI entrypoint
  graph.py               # LangGraph state machine
  state.py               # Typed state schema
  llm.py                 # Gemini + OpenRouter clients
  agents/
    triage.py            # Classify + scope the issue
    mapper.py            # Clone repo, build AST index
    retriever.py         # Hybrid BM25 + dense + graph
    planner.py           # Structured JSON plan
    reproducer.py        # Synthesise failing test
    patcher.py           # ReAct loop with code tools
    critic.py            # Reflexion: ship / revise / abort
    pr_writer.py         # PR title + body generator
  tools/
    fs.py                # read_file, write_file, list_dir
    grep.py              # ripgrep-style search
    ast_go.py            # tree-sitter Go: symbols, refs
    git_ops.py           # branch, diff, apply
    go_toolchain.py      # gofmt, go vet, go build, go test
    github_api.py        # issue fetch, PR scrape
  rag/
    indexer.py           # AST-aware chunker
    bm25.py              # rank-bm25 wrapper
    dense.py             # sentence-transformers + ChromaDB
    hybrid.py            # weighted fusion
    convention_learner.py
  guardrails/
    policy.py            # Path / size / pattern bans
    ast_check.py         # Patched files must parse
    validator.py         # go vet / build / test runner
prompts/                 # All system prompts as standalone files
docs/APPROACH.md         # Design rationale + stack trade-offs
examples/                # Replayable issue fixtures
tests/                   # Unit tests for tools + agents
```

---

## Tests

```bash
pytest -q                          # tool unit tests
python -m go_contributor run --fixture examples/gin_3936   # end-to-end smoke
```

---

## Limits & honest caveats

* **Scope**: small/medium issues only. Architectural changes are explicitly refused by the triage agent.
* **Cost**: ~$0 on Gemini's free tier for one issue (~50–80k tokens). The local embedding model and BM25
  mean retrieval is free.
* **Determinism**: `temperature=0.1` and a fixed retrieval seed get you ~stable outputs across runs, but the
  ReAct loop is not bit-identical.
* **Go toolchain required**: validator runs the real Go compiler. If `go` is not on `PATH`, the validator
  emits a single "no go toolchain" warning and the critic decides on the diff alone (still useful for review,
  but obviously weaker).

See [`docs/APPROACH.md`](docs/APPROACH.md) for the full discussion of why each piece of the stack was chosen
over the alternatives.
