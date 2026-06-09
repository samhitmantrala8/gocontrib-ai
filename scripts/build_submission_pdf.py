"""Build the final submission PDF.

Sections:
  1. Title page + summary
  2. Problem statement
  3. Stack and why each piece
  4. Architecture diagram (text)
  5. Component-by-component design rationale
  6. Test results (pytest output)
  7. Model probe results (which Gemini and OpenRouter models work)
  8. Sample agent run on a real issue (validator#1517) with patch + PR
  9. Limitations and future work
 10. Repo layout

Avoids em dashes per the user's request.
"""

from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image as RLImage,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PDF_OUT = ROOT / "GoContrib_AI_Submission.pdf"


def _no_em_dash(s: str) -> str:
    # Per user request, no em dashes (U+2014) anywhere in the doc. We do NOT
    # touch ``--`` because that pattern is used in box-drawing ASCII art and
    # in unified diff hunks, where rewriting it would corrupt the meaning.
    return s.replace("—", ", ").replace("–", "-")


def _read(path: Path, fallback: str = "(file missing)") -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return fallback


def _styles():
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "body",
        parent=base["BodyText"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=14,
        spaceAfter=6,
        alignment=TA_LEFT,
    )
    h1 = ParagraphStyle(
        "h1",
        parent=base["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        spaceAfter=10,
        textColor=colors.HexColor("#1a3a5c"),
    )
    h2 = ParagraphStyle(
        "h2",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13.5,
        leading=18,
        spaceBefore=10,
        spaceAfter=6,
        textColor=colors.HexColor("#1a3a5c"),
    )
    h3 = ParagraphStyle(
        "h3",
        parent=base["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=11.5,
        leading=15,
        spaceBefore=8,
        spaceAfter=4,
        textColor=colors.HexColor("#324d6b"),
    )
    title = ParagraphStyle(
        "title",
        parent=base["Title"],
        fontName="Helvetica-Bold",
        fontSize=26,
        leading=30,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#0d2545"),
    )
    subtitle = ParagraphStyle(
        "subtitle",
        parent=base["BodyText"],
        fontName="Helvetica",
        fontSize=12,
        leading=16,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#324d6b"),
        spaceAfter=12,
    )
    code = ParagraphStyle(
        "code",
        parent=base["Code"],
        fontName="Courier",
        fontSize=8.5,
        leading=10.5,
        backColor=colors.HexColor("#f4f4f4"),
        borderColor=colors.HexColor("#dddddd"),
        borderWidth=0.5,
        borderPadding=4,
    )
    return {"body": body, "h1": h1, "h2": h2, "h3": h3, "title": title,
            "subtitle": subtitle, "code": code}


def _bullets(items: list[str], st: dict) -> list:
    out = []
    for it in items:
        out.append(Paragraph("• " + _no_em_dash(it), st["body"]))
    return out


def _para(text: str, st_body) -> Paragraph:
    return Paragraph(_no_em_dash(text), st_body)


def _code_block(text: str, st_code, *, max_lines: int = 60) -> Preformatted:
    lines = text.splitlines()
    if len(lines) > max_lines:
        keep = lines[: max_lines - 1]
        keep.append(f"... ({len(lines) - max_lines + 1} more lines truncated for brevity)")
        text = "\n".join(keep)
    return Preformatted(text, st_code)


def _screenshot(rel: str, max_width: float = 6.6 * inch) -> RLImage | None:
    p = ROOT / rel
    if not p.exists():
        return None
    img = RLImage(str(p))
    iw, ih = img.imageWidth, img.imageHeight
    if iw > max_width:
        scale = max_width / iw
        img.drawWidth = max_width
        img.drawHeight = ih * scale
    return img


def _table(rows: list[list[str]], col_widths: list[float], st: dict) -> Table:
    data = [[Paragraph(_no_em_dash(c), st["body"]) for c in row] for row in rows]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#f7f9fc")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    return t


def build_doc(out: Path) -> None:
    st = _styles()
    doc = SimpleDocTemplate(
        str(out),
        pagesize=LETTER,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title="GoContrib-AI Submission",
        author="Samhit Mantrala",
    )
    story: list = []

    # ---------- Title page ----------
    story += [
        Spacer(1, 1.4 * inch),
        Paragraph("GoContrib-AI", st["title"]),
        Spacer(1, 0.18 * inch),
        Paragraph("An Agentic AI Contributor for Open-Source Go Projects", st["subtitle"]),
        Spacer(1, 0.6 * inch),
        Paragraph("Take-home submission", st["subtitle"]),
        Paragraph("Samhit Mantrala", st["subtitle"]),
        Spacer(1, 0.3 * inch),
    ]

    summary_rows = [
        ["What it does",
         "Takes a GitHub issue from gin, cobra, validator, or golangci-lint and produces a "
         "minimal patch plus a PR title and body. Does the inspect, plan, edit, validate, "
         "explain loop end to end, locally, with no human in the loop after the run starts."],
        ["Built around",
         "LangGraph state machine, ReAct patcher, Reflexion critic, hybrid RAG over Go AST, "
         "three layers of guardrails."],
        ["LLMs",
         "Gemini 2.5 Flash family as primary, OpenRouter (DeepSeek, Llama 3.3 70B, GPT-4o-mini) "
         "as fallback. The runtime rotates across keys and models on rate limit."],
        ["RAG stack",
         "Tree-sitter-go for symbol level chunks, BM25 plus MiniLM dense embeddings stored in "
         "ChromaDB plus one hop call graph expansion. Local only, no Pinecone account needed."],
        ["Tested on",
         "go-playground/validator issue #1517, end to end. Produced a 13 line patch that builds "
         "clean and passes go vet."],
    ]
    story.append(_table([["Section", "Summary"]] + summary_rows,
                        col_widths=[1.4 * inch, 5.4 * inch], st=st))
    story.append(PageBreak())

    # ---------- Problem statement ----------
    story.append(Paragraph("1. Problem statement", st["h1"]))
    story.append(_para(
        "Build an agentic AI platform that can work on issues from open-source Go projects "
        "and generate production quality code changes. The brief explicitly says the evaluators "
        "want to see the system around the LLM, not a one-shot prompt or thin wrapper.",
        st["body"]))
    story.append(_para("The system has to do all of the following on its own:", st["body"]))
    story += _bullets([
        "Inspect the repository.",
        "Understand the issue.",
        "Identify the relevant files and surrounding context.",
        "Plan the fix.",
        "Modify the code.",
        "Run validation, gofmt, vet, build, focused tests.",
        "Generate a PR title and body.",
    ], st)
    story.append(_para(
        "Approved repositories are gin-gonic/gin, spf13/cobra, go-playground/validator, "
        "and golangci/golangci-lint. The brief asks for small or medium issues only. "
        "It also reminds us that a simple thoughtful framework that solves focused issues "
        "reliably is preferred over a complex system that is unreliable.",
        st["body"]))

    # ---------- Stack ----------
    story.append(Paragraph("2. Stack and why each piece", st["h1"]))
    rows = [
        ["Concern", "Choice", "Why this and not the alternative"],
        ["Orchestration", "LangGraph",
         "Explicit typed state graph. Edges encode routing. Loops, retries, and "
         "checkpointing are first class. LangChain AgentExecutor hides control flow "
         "inside the prompt which makes failure modes unpredictable. AutoGen and "
         "CrewAI optimise for multi agent conversation, but coding tasks are a "
         "deterministic pipeline so conversation is overhead."],
        ["Agent pattern", "ReAct plus Reflexion",
         "ReAct lets the patcher explore the repo through tools before editing. "
         "Reflexion gives the critic a way to feed structured feedback back to the "
         "patcher so it can revise instead of retrying blind. We bound the revise "
         "loop at three iterations."],
        ["LLM primary", "Gemini 2.5 Flash family",
         "Generous free tier on AI Studio, JSON mode, low latency. We try lite first "
         "since its quota is the most generous, then full Flash, then 2.0 Flash."],
        ["LLM fallback", "OpenRouter",
         "OpenAI compatible API, lots of models on one key. We rotate through "
         "DeepSeek, Llama 3.3 70B, and GPT-4o-mini. The runtime auto switches when "
         "the entire Gemini key pool returns 429."],
        ["Embeddings", "sentence-transformers MiniLM L6 v2",
         "80 MB, CPU only, no API call at inference. Plenty of signal for issue "
         "text to symbol matching on 3 to 15k symbol Go repos. OpenAI ada is better "
         "quality but adds a paid network call inside every retrieval. CodeBERT and "
         "instructor large are marginally better on syntactic similarity but not on "
         "the specific shape of query we need."],
        ["Vector DB", "ChromaDB local persistent",
         "Single developer scale. Pinecone earns its keep at multi tenant scale, "
         "where you actually need a managed service. Adding a Pinecone account "
         "would force every reviewer to sign up just to run the system. The "
         "HybridRetriever takes any object exposing query so swapping it for "
         "Pinecone is a 30 line module."],
        ["Lexical retrieval", "rank-bm25 with Go aware tokenizer",
         "Issue authors quote exact symbol names. Lexical wins for that. Tokenizer "
         "splits camelCase plus snake_case plus dotted, and lowercases everything."],
        ["Symbol parser", "tree-sitter-go",
         "Same parser GitHub uses for code navigation. Robust to half broken files. "
         "Lets us chunk on whole functions, methods, and types instead of token "
         "windows."],
        ["Repo I/O", "GitPython plus git CLI",
         "GitPython for porcelain like clone and branch. Plain git CLI for diff and "
         "reset because that is much simpler than wrapping it."],
        ["Validator", "Go toolchain shell out",
         "One source of truth. Exactly what CI will run. We ran gofmt only on the "
         "files we touched so unrelated upstream files that happen to be unformatted "
         "do not produce false positives."],
        ["Convention learning", "GitHub PR scrape plus LLM distil",
         "We pull the last 15 merged PRs and have the LLM produce 200 words of "
         "directives. Cheaper than RAGing prose, fits in one prompt."],
    ]
    story.append(_table(rows, col_widths=[1.3 * inch, 1.4 * inch, 4.1 * inch], st=st))

    story.append(PageBreak())

    # ---------- Architecture diagram (ASCII) ----------
    story.append(Paragraph("3. Architecture", st["h1"]))
    story.append(_para(
        "Eight specialised agent nodes connected by a LangGraph state machine. State "
        "is a single typed dictionary which every node reads and writes through "
        "documented keys. Routing decisions live at the edges, not inside prompts.",
        st["body"]))
    story.append(_code_block("""\
   Step  Node          Reads from state            Writes to state
   ----  ------------  --------------------------  -----------------------------
   1     triage        issue                       in_scope, issue_kind
   2     mapper        issue                       repo_path, repo_indexed
   3     retriever     issue, repo_path            retrieved, conventions
   4     planner       issue, retrieved            plan
   5     reproducer    plan, repo_path             repro_test_path, repro_failed
   6     patcher       plan, retrieved, feedback   diff, files_touched
   7     guardrails    diff, files_touched         guardrail_violations
   8     validator     repo_path, files_touched    validation
   9     critic        diff, validation, plan      critic verdict (ship,
                                                    revise, abort)
  10     pr_writer     diff, plan, validation      pr_title, pr_body

   Routing edges:
       triage:   in_scope=False                ->   abort
       triage:   in_scope=True                 ->   mapper
       critic:   verdict=ship                  ->   pr_writer
       critic:   verdict=revise && loops<cap   ->   patcher (with feedback)
       critic:   verdict=abort                 ->   abort
""", st["code"], max_lines=40))

    # ---------- Per component ----------
    story.append(Paragraph("4. Component design rationale", st["h1"]))
    story.append(Paragraph("4.1  Why a separate planner instead of one giant agent", st["h2"]))
    story.append(_para(
        "A separate planner is the single biggest reliability win. The plan is JSON "
        "so it is cheap to validate and retry. Having target_files in state means "
        "the validator only runs tests for the affected packages, not ./... which is "
        "slow on cobra and golangci-lint. The critic can compare did the diff match "
        "the planned intent and reject wrong fixes that happen to compile.",
        st["body"]))

    story.append(Paragraph("4.2  Why a reproducer node", st["h2"]))
    story.append(_para(
        "Before patching, the system asks the LLM to write a Go test that should "
        "fail because of the bug, then runs it. If it fails as expected, the patcher "
        "has a runnable target and the validator after the patch will re run that "
        "test as a regression check. If it passes on first run, the planner "
        "hypothesis is probably wrong, and we record this so the critic can see it "
        "on the revise loop. Cost is one extra LLM call plus one go test run. It "
        "skips itself cleanly when go is not on PATH or when the issue is a doc fix.",
        st["body"]))

    story.append(Paragraph("4.3  Why hybrid retrieval", st["h2"]))
    story.append(_para(
        "Three layers fused with normalised scores: BM25 catches exact identifier "
        "hits like the issue saying BindJSON; dense catches paraphrased intent like "
        "the issue saying parse the body; one hop symbol graph expansion catches "
        "the next symbol the patcher will need, like a helper function called from "
        "the buggy function. Each contribution is normalised to zero one before "
        "fusion so the weights in config.yaml are intuitive and not tied to the "
        "absolute score scale of any one ranker.",
        st["body"]))

    story.append(Paragraph("4.4  Why symbol level chunks instead of fixed window splits", st["h2"]))
    story.append(_para(
        "The standard RAG default of splitting on token windows is wrong for code. "
        "A token window can split a Go function in half. The LLM gets the second "
        "half without the signature, types, or imports, and confidently writes a fix "
        "against a phantom context. Instead we chunk on AST symbols using "
        "tree-sitter-go. Each chunk carries qualified_name, kind, start_line, and "
        "end_line. Every retrieved chunk is a whole compilable unit of Go.",
        st["body"]))

    story.append(Paragraph("4.5  Three layers of guardrails", st["h2"]))
    story += _bullets([
        "Layer 1 policy.check_write runs before every write_file call. "
        "Banned paths like vendor, .github/workflows, go.mod, and banned content "
        "patterns like panic and os.Exit. About one millisecond.",
        "Layer 2 ast_check.check_files runs after the patcher finishes, before the "
        "validator. Re-parses every patched .go with tree-sitter and rejects if any "
        "ERROR nodes are present. Catches the long tail of the LLM dropped a brace "
        "failures cheaply.",
        "Layer 3 validator.run is the slow one. gofmt on touched files only, go vet, "
        "go build, focused go test for the affected packages. Only runs once "
        "layers 1 and 2 passed.",
    ], st)
    story.append(_para(
        "The order matters. A runaway LLM that overwrites a workflow YAML is caught "
        "by layer 1 in milliseconds and never reaches go build which takes 30 "
        "seconds. When the critic sees a parse failure or a banned path violation, "
        "it short circuits without burning an LLM call.",
        st["body"]))

    story.append(Paragraph("4.6  Multi key, multi model rotation", st["h2"]))
    story.append(_para(
        "GEMINI_API_KEYS and OPENROUTER_API_KEYS are both comma separated. The "
        "runtime builds a flat call plan of provider key model triples and walks "
        "down it on every LLM call, marking exhausted combos with a 60 second "
        "cooldown. This is what keeps a long ReAct loop alive on the free tier. "
        "When the whole Gemini fleet returns 429, we cross over to OpenRouter "
        "automatically, with no code change required.",
        st["body"]))

    story.append(PageBreak())

    # ---------- Test results ----------
    story.append(Paragraph("5. Unit test results", st["h1"]))
    story.append(_para(
        "Twenty six unit tests cover the file system tool, ripgrep style search, "
        "tree-sitter symbol extraction and parse check, BM25 with Go aware "
        "tokenisation, hybrid retriever fusion plus graph expansion, the policy "
        "guardrail, the lenient JSON parser, and the LangGraph topology end to end "
        "with stub agents. All twenty six pass.",
        st["body"]))
    img = _screenshot("docs/pytest_screenshot.png")
    if img is not None:
        story.append(img)
        story.append(Spacer(1, 0.1 * inch))
    story.append(_code_block(_read(DOCS / "test_output.txt"), st["code"], max_lines=40))

    # ---------- Model probe ----------
    story.append(Paragraph("6. Live LLM probe results", st["h1"]))
    story.append(_para(
        "scripts/probe_models.py calls every Gemini and OpenRouter model in "
        "config.yaml with each key and reports which combinations actually answer. "
        "Six of eight combinations work on the keys provided. The two that do not "
        "work are caught by the runtime and skipped: gemini-2.0-flash is rate "
        "limited, and google/gemini-flash-1.5 has no endpoints behind it on this "
        "OpenRouter account. The runtime keeps walking down the list until something "
        "responds, so the user does not see those failures during a real run.",
        st["body"]))
    img = _screenshot("docs/probe_screenshot.png")
    if img is not None:
        story.append(img)
        story.append(Spacer(1, 0.1 * inch))
    story.append(_code_block(_read(DOCS / "model_probe_results.txt"), st["code"], max_lines=20))

    story.append(PageBreak())

    # ---------- Sample run ----------
    story.append(Paragraph("7. Sample run on a real issue", st["h1"]))
    story.append(_para(
        "Issue: go-playground/validator number 1517, titled \"Removal of BGN ccy "
        "from the list\". The body says Bulgaria adopts the Euro on 1 January 2026 "
        "so the BGN currency code should leave the ISO 4217 validation list. "
        "This is a tiny single file edit in currency_codes.go.",
        st["body"]))

    story.append(Paragraph("7.1  Console output (screenshot)", st["h3"]))
    img = _screenshot("docs/sample_run_screenshot.png")
    if img is not None:
        story.append(img)
        story.append(Spacer(1, 0.1 * inch))
    story.append(_code_block(_read(DOCS / "sample_run_1517_log.txt"), st["code"], max_lines=60))

    story.append(Paragraph("7.2  Generated patch", st["h3"]))
    story.append(_code_block(_read(DOCS / "sample_run_1517_patch.diff"), st["code"], max_lines=30))

    story.append(Paragraph("7.3  Generated PR title and body", st["h3"]))
    story.append(_code_block(_read(DOCS / "sample_run_1517_pr.md"), st["code"], max_lines=20))

    story.append(Paragraph("7.4  Trace summary", st["h3"]))
    trace_text = _read(DOCS / "sample_run_1517_trace.json")
    # Compact the trace down to a per node summary so the PDF stays readable.
    import json as _j
    try:
        nodes = _j.loads(trace_text)
        summary_lines = []
        for n in nodes:
            node = n.get("node", "?")
            extras = []
            for k, v in n.items():
                if k == "node":
                    continue
                if k == "top":
                    extras.append(f"top={len(v)} chunks")
                    continue
                vstr = _j.dumps(v, ensure_ascii=False)
                if len(vstr) > 140:
                    vstr = vstr[:140] + "..."
                extras.append(f"{k}={vstr}")
            summary_lines.append(f"- {node}: " + ", ".join(extras))
        compact = "\n".join(summary_lines)
    except Exception:
        compact = trace_text
    story.append(_code_block(compact, st["code"], max_lines=40))

    story.append(Paragraph("7.5  Post run validation", st["h3"]))
    story.append(_para(
        "Ran go build ./... and go vet ./... on the patched worktree. Both passed "
        "clean. The agent's critic node also reached the ship verdict on revise "
        "loop three after gofmt was scoped to touched files only.",
        st["body"]))

    story.append(PageBreak())

    # ---------- Limitations ----------
    story.append(Paragraph("8. Honest limitations and where this would fail", st["h1"]))
    story += _bullets([
        "Issue selection still matters. The triage agent rejects most rewrite the "
        "parser style requests but the small or medium framing is on the user.",
        "No long horizon memory across runs other than the convention cache and "
        "the dense index. Each issue is solved from scratch.",
        "go test is slow on golangci-lint. We run focused tests by default but a "
        "wide touching plan reverts to ./... which can take a couple of minutes.",
        "Large rewrites can blow through the LLM output token cap when the patcher "
        "tries to use write_file. We added a replace_in_file tool which is the "
        "preferred path and avoids this whenever the change is localised.",
        "Gemini 2.5 Flash sometimes returns finish_reason MAX_TOKENS even on "
        "small prompts because it spends tokens on hidden reasoning. The runtime "
        "treats those as recoverable and rotates to the next combo.",
    ], st)

    # ---------- Future work ----------
    story.append(Paragraph("9. Where to extend next", st["h1"]))
    story += _bullets([
        "AST level diff editor exposing replace_symbol so the LLM can never mangle "
        "untouched code.",
        "Contrastive retrieval pass that surfaces similar but wrong symbols and "
        "tells the patcher do not be these.",
        "Few shot exemplar from a real merged PR that touched the same file. We "
        "already pull the GitHub PR list for the convention learner.",
        "Pluggable validator profiles per project. golangci-lint has its own "
        "linter config, cobra has make test, gin has make test.fast.",
        "Nightly CI workflow that runs the agent against a curated issue list and "
        "posts a Markdown summary, turning this into an evaluation harness for "
        "itself.",
    ], st)

    # ---------- Repo layout ----------
    story.append(Paragraph("10. Repo layout", st["h1"]))
    story.append(_code_block(_no_em_dash("""\
src/go_contributor/
  __main__.py            CLI entry point
  graph.py               LangGraph state machine
  state.py               typed state schema
  llm.py                 multi key, multi model client with rotation
  agents/
    triage.py            classify and scope the issue
    mapper.py            clone repo, build AST index
    retriever.py         hybrid BM25 + dense + graph
    planner.py           structured JSON plan
    reproducer.py        synth a failing Go test first
    patcher.py           ReAct loop with read, grep, find_symbol, replace_in_file, write_file
    critic.py            Reflexion: ship, revise, abort
    pr_writer.py         PR title and body
  tools/
    fs.py                path safe file system
    grep.py              ripgrep style search
    ast_go.py            tree-sitter-go: symbols and call graph
    git_ops.py           branch, diff, apply
    go_toolchain.py      gofmt scoped to touched files, go vet, go build, go test
    github_api.py        issue fetch, recent merged PR scrape
  rag/
    indexer.py           AST aware chunker
    bm25.py              rank-bm25 wrapper with Go aware tokenizer
    dense.py             sentence-transformers + ChromaDB
    hybrid.py            weighted fusion
    convention_learner.py
  guardrails/
    policy.py            path, size, pattern bans
    ast_check.py         patched files must parse
    validator.py         go vet, build, focused tests
prompts/                 standalone .md files, one per agent
docs/APPROACH.md         long form rationale
examples/                replayable issue fixtures
tests/                   pytest unit tests
scripts/
  probe_models.py        live model probe
  build_submission_pdf.py this PDF
"""), st["code"], max_lines=120))

    doc.build(story)


if __name__ == "__main__":
    build_doc(PDF_OUT)
    print(f"wrote {PDF_OUT}")
