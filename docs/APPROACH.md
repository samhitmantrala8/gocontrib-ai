# Approach and design rationale

This is the long-form companion to the README. The README tells you what
the system does. This document explains why every choice was made, what
the alternatives were, and where the system is deliberately weaker than
the alternatives in exchange for being simpler to run and easier to trust.

## 1. Problem framing

The take-home asks for an agentic AI contributor for four specific Go
repos. Two lines from the brief shaped the design more than anything else:

> "we expect to see the system or framework you built around it, not just
> a one-shot prompt or thin wrapper."

> "A simple, thoughtful framework that can solve focused issues reliably
> is better than a complex system that is hard to understand or unreliable."

So the design is built around two non-negotiables.

1. Visible structure. The orchestration is an explicit graph with a typed
   state schema. You can read `graph.py` end to end in a minute and know
   what every node does.
2. Reliability before ambition. When in doubt, the system aborts safely
   instead of producing a confidently-wrong patch. Guardrails run before
   slow validators, and the critic prefers `revise` over `abort` only
   when the patch is plausibly fixable.

Everything below flows from those two constraints.

## 2. Stack at a glance and why each piece

| Concern             | Choice                                  | Why this and not the alternative                                  |
|---------------------|-----------------------------------------|-------------------------------------------------------------------|
| Orchestration       | LangGraph (typed state machine)         | Explicit edges, easy to reason about, supports loops and retries. |
| Agent pattern       | ReAct (patcher) plus Reflexion (critic) | ReAct gives tool selection, Reflexion gives a learning loop.      |
| LLM primary         | Gemini 2.5 Flash family (free tier)     | Generous free quota, fast, JSON mode, strong on Go.               |
| LLM fallback        | OpenRouter, DeepSeek, Llama 3.3, GPT-4o-mini | Auto-engaged when the Gemini pool returns 429.               |
| Embeddings          | sentence-transformers MiniLM-L6-v2      | 80 MB, CPU only, no API call. Plenty for 3 to 15k Go symbols.     |
| Vector DB           | ChromaDB local persistent               | Single-developer scale, no Pinecone account or quota or latency.  |
| Lexical retrieval   | rank-bm25 with Go-aware tokenizer       | Issue authors quote exact symbol names. Lexical wins.             |
| Symbol parser       | tree-sitter-go                          | Same parser GitHub uses, robust to half-broken files.             |
| Repo I/O            | GitPython plus git CLI                  | GitPython for porcelain, CLI for diff and reset. Faster, simpler. |
| Validator           | Go toolchain shell-out                  | One source of truth. Exactly what CI will run.                    |
| Convention learning | GitHub PR scrape plus LLM distil        | Cheaper than RAGing prose, output fits in one prompt.             |
| CLI                 | Typer plus Rich                         | Standard, hackable, pretty traces during a run.                   |
| Tests               | pytest                                  | Standard.                                                         |

The next sections argue each row in detail.

## 3. Why LangGraph and not LangChain agents, AutoGen, CrewAI, or hand-rolled

LangGraph models an agent system as a typed state graph instead of "a
chain of agents who chat with each other". For this problem that matters
in three ways.

* Conditional edges live at the graph level, not inside agent prompts.
  When the critic returns `revise`, the graph routes back to the patcher.
  We do not have to teach the patcher "if I get rejected, ask the patcher
  again". That is a topology question, not a prompting question.
* State is typed and inspectable. `state.py` is the contract. Every node
  reads explicit keys and writes explicit keys. The trace is just an
  append log of what each node touched. Debugging an agent run becomes
  reading a JSON file, not re-running the prompt.
* Retries and loop bounds are first class. `max_revise_loops` is one
  number in `config.yaml`, enforced by an edge condition, not a prompt
  caveat the LLM might forget.

Alternatives considered.

* LangChain `AgentExecutor`. Too implicit. The control flow lives inside
  the LLM prompt, which makes "what happens after a tool fails" depend on
  what the model felt like that turn.
* AutoGen and CrewAI. Both lean on multi-agent conversation. For a coding
  task with a deterministic pipeline, conversation is overhead. We do not
  need agents to negotiate, we need them to do their step and pass.
* Hand-rolled Python loop. Fine, but reinventing checkpointing,
  conditional edges, state typing, and trace recording is 200 lines we
  would rather not maintain.

## 4. Agent pattern: ReAct plus Reflexion, not one giant prompt

### 4.1 Why ReAct in the patcher

The patcher needs to explore the repo before editing: find a symbol, read
a file, grep for a usage. ReAct's reason, action, observation loop is the
cheapest pattern that supports this.

* Each action is a JSON tool call our runtime executes.
* The observation is structured (truncated to 5 KB, never raw stdout).
* The loop terminates on `{"tool":"finish"}` or after `max_react_steps`.

We deliberately keep the tool surface to six tools. Bigger menus make
small models pick the wrong tool. The six are: `read_file`, `list_dir`,
`grep`, `find_symbol`, `replace_in_file`, and `write_file`, plus `finish`
to end the loop. `replace_in_file` is preferred. It refuses if the `old`
substring is not in the file, so the model cannot silently drop the rest
of the file. It also refuses if the `old` substring is ambiguous, forcing
the model to add context until the match is unique.

### 4.2 Why Reflexion in the critic

After the patcher finishes, the critic sees:

* the diff
* the validator output (gofmt, vet, build, focused tests)
* the post-patch policy and AST checks

It returns one of `ship`, `revise`, `abort`. On `revise`, its rationale
and suggestions flow back to the patcher as `revise_feedback`. The
patcher sees: your previous attempt was rejected because X, try again.
That is the Reflexion idea. A model performs better when it sees a
structured critique of its own previous attempt, not when it just retries
blind.

Bound: 3 revise loops by default. After that we abort with the trace.
Better to admit defeat than to burn tokens on a stuck agent.

### 4.3 Why a separate planner instead of "patcher does it all"

A separate planner is the single biggest reliability win.

* The planner emits JSON, so we can validate its output cheaply.
* The plan is small and fits in one LLM call, cheap to retry on rate
  limit.
* Having `target_files` and `target_symbols` in state means the validator
  only runs tests for the affected packages, not `./...`, which is slow
  and noisy on cobra and golangci-lint.
* The critic compares "did the diff match the planned intent" and can
  reject "wrong fix that compiles" cases that a single-prompt agent
  misses.

### 4.4 Why a reproducer node

The novel piece. Before patching, the system asks the LLM to write a Go
test that should fail because of the bug, then runs it.

* If it fails as expected, the patcher has a runnable target, and the
  validator after the patch will re-run the test as a regression check.
* If it passes on first run, the planner's hypothesis is probably wrong.
  We record this and the critic sees it on the revise loop.

Cost: one extra LLM call plus one `go test` run. Benefit: catches "we are
fixing the wrong thing" failures before spending a 12-step ReAct loop on
the wrong file. The node skips itself cleanly when `go` is not on PATH or
when the issue is a doc fix.

## 5. RAG: hybrid (BM25 + dense + symbol-graph)

This is the second piece worth calling out for the assignment.

### 5.1 Why symbol-level chunks instead of fixed-window splits

The standard RAG default ("split on 1024-token windows with 128-token
overlap") is wrong for code. A token window can split a Go function in
half. The LLM gets the second half without the signature, types, or
imports, and confidently writes a "fix" against a phantom context.

Instead, we chunk on AST symbols using tree-sitter-go.

* one chunk per function, method, or type declaration
* the chunk carries `qualified_name`, `kind`, `start_line`, `end_line`
* oversized symbols (rare) fall back to a sliding window inside the
  symbol

Result: every retrieved chunk is a whole, compilable unit of Go. The LLM
can reason about it without missing context.

### 5.2 Why BM25 plus dense plus graph

| Layer  | What it is good at                                   | What it misses                            |
|--------|------------------------------------------------------|-------------------------------------------|
| BM25   | Exact identifier hits (issue says `BindJSON`).       | Paraphrased intent ("parse the body...")  |
| Dense  | Semantic match, paraphrasing, "code that does X".    | Identifiers it has never seen.            |
| Graph  | Caller and callee one-hop expansion.                 | Cold start, returns nothing on its own.   |

BM25 alone is surprisingly competitive for this task because issue
authors quote the symbol name. Dense alone misses identifiers it did not
see during pretraining. The fusion is consistently better than either.

The graph layer is cheap (tree-sitter already gave us callees) and pulls
in the next symbol the patcher will need. That matters when the bug is
in function A but the fix lives in helper B.

### 5.3 Why ChromaDB local instead of Pinecone

* Free, no account, no per-query latency.
* Persistent on disk between runs. The second run on the same repo skips
  the embedding step entirely.
* Single-user scale. Pinecone earns its keep at multi-tenant scale,
  where you actually need the managed service.

If a team wanted a shared cache across machines, the `HybridRetriever`
takes any object exposing `query(text, top_k) -> list[Hit]`, so swapping
ChromaDB for Pinecone is a 30-line module. We just do not ship with that
as the default because it would force every reviewer to create a Pinecone
account to run our system.

### 5.4 Why MiniLM-L6-v2 over CodeBERT, instructor-large, OpenAI ada

* MiniLM is 80 MB, CPU only, about 1 ms per query after warmup. The kind
  of thing you want running inside a tool loop.
* Code-specific embeddings (CodeBERT, e5-base-v2-code) are marginally
  better on syntactic similarity but not better on issue-text to symbol
  matching, which is the actual query shape here.
* OpenAI ada would be excellent quality but requires an API key, paid
  tokens, and adds a network call inside retrieval. Worse fit for the
  "easy to run" deliverable target.

## 6. Guardrails: defence in depth

Three layers, each cheaper than the next.

1. `policy.check_write` runs before every `write_file` or
   `replace_in_file` tool call. Banned paths (`vendor/`,
   `.github/workflows/`, `go.mod` unless allowed), banned content patterns
   (`panic(`, `os.Exit(`).
2. `policy.check_diff` plus `ast_check.check_files` run after the patcher
   finishes, before the slow validator. Catches "more than 8 files
   touched", "diff > 400 lines", "patched file no longer parses".
3. `validator.run` is the slowest layer. `gofmt` on touched files only,
   `go vet`, `go build`, focused `go test` for affected packages. Only
   invoked once cheaper layers passed.

The order matters. A runaway LLM that overwrites a workflow YAML is
caught by layer 1 in milliseconds and never reaches `go build` (~30s).
When the critic sees a failure from layer 1 or 2, it short-circuits. The
LLM critic does not get called for "patch does not parse". That is a
fact, not a judgement. Saves a token round trip.

## 7. Convention learner

On first use against a repo, we hit
`/repos/{repo}/pulls?state=closed&sort=updated` and grab the last 15
merged PRs. Their titles and bodies go into one Gemini call that emits
under 200 words of distilled conventions ("commit titles use imperative,
tests are table-driven, errors wrapped with `fmt.Errorf(\"%w\")`").

The output is cached to disk per repo, so this only happens once. The
patcher prompt and the PR-writer prompt both consume it.

Why not a long structured rules file? Because long context dilutes
attention. 200 words of project-specific directives outperforms 5000
words of "general Go style".

## 8. LLM choice: Gemini, with OpenRouter fallback

* Why Gemini 2.5 Flash family as primary. Free tier is generous,
  `response_mime_type=application/json` works, latency is low, quality on
  Go is strong. We try `gemini-2.5-flash-lite` first because its quota is
  the most generous in our probe.
* Why OpenRouter as fallback. When the primary returns 429 mid run, we
  auto-switch. OpenRouter's OpenAI-compatible API means one shared client
  shape. `deepseek/deepseek-chat` is around $0.14 per million input
  tokens, pennies for one issue.
* Why temperature 0.1. We want stable plans and diffs across runs. Not
  zero, because zero sometimes makes Gemini repeat itself in a loop.
* Why multi-key rotation. The runtime accepts comma-separated
  `GEMINI_API_KEYS` and `OPENROUTER_API_KEYS`, builds a flat call plan of
  (provider, key, model) triples, and walks it on every LLM call,
  marking exhausted combos with a 60-second cooldown. This is what keeps
  a long ReAct loop alive on the free tier.

## 9. What we deliberately did not build

These were tempting and dropped on purpose.

* Multi-agent debate (e.g. two patcher agents arguing). The critic loop
  is enough. Debate adds tokens without adding signal on small fixes.
* Auto-PR opener. The brief explicitly says a local diff is fine, and
  pushing branches is a side effect we do not want our agent making
  silently. The user pushes when they are happy.
* Fine-tuning a code model. Out of scope and unnecessary for the size of
  issues we target. Retrieval plus ReAct framing carries the weight.
* A web UI. A CLI plus a `trace.json` is faster to review and easier to
  drop into CI later.
* Tool calls as native function-calling. Gemini supports it, but emitting
  JSON tool actions in plain text keeps the same code path working with
  OpenRouter and DeepSeek, and makes the trace human-readable.

## 10. Honest limitations

* Issue selection still matters. The triage agent rejects most "rewrite
  the parser" requests, but the small or medium framing is on the user.
* No long-horizon memory across runs beyond the convention cache and the
  dense index. Each issue is solved from scratch.
* `go test ./...` is slow on golangci-lint. We run focused tests by
  default (only the package the plan touched) but a wide-touching plan
  reverts to `./...` and that can take a couple of minutes.
* Rate limits still bite on Gemini's free tier when the ReAct loop goes
  long. The fallback exists for exactly this reason. The README surfaces
  the toggle prominently.

## 11. Where to extend next

If we had another week.

1. AST-level diff editor. Instead of `write_file`, expose
   `replace_symbol(name, new_body)` so the LLM cannot mangle untouched
   code.
2. Contrastive retrieval pass. Surface symbols that are similar but the
   wrong fix and tell the patcher "do not be these".
3. Exemplar-shot from a real merged PR that touched the same file. We
   already have the GitHub PR list, so this is trivial to wire as
   few-shot context.
4. Pluggable validator profiles per project. golangci-lint has its own
   linter config, cobra has `make test`, gin has `make test.fast`.
5. CI workflow that runs the agent against a curated issue list each
   night and posts a Markdown summary. Turns the system into an
   evaluation harness for itself.

## 12. TL;DR for reviewers in a hurry

* Why this is more than a wrapper. Typed state machine, eight
  specialised agents, AST-level RAG, reproducer-test-first, Reflexion
  critic loop, three layers of guardrails. Reading `graph.py` and
  `state.py` is enough to understand the whole system.
* Why the stack is right-sized. Every external dependency was picked to
  keep the system runnable on a laptop with no paid accounts and one
  free API key. ChromaDB instead of Pinecone, MiniLM instead of OpenAI
  embeddings, Gemini Flash free tier instead of GPT-4.
* Why it is safe to run. Patches go through pre-write policy, then AST
  must-parse, then focused validator, then LLM critic, in that order.
  The slowest check runs last. The cheapest checks run on every write.
