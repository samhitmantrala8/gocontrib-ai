from go_contributor.rag.bm25 import BM25Index, tokenize
from go_contributor.rag.indexer import Chunk


def test_camel_case_tokenisation():
    toks = tokenize("BindJSON")
    assert "bindjson" in toks
    assert "bind" in toks
    assert "json" in toks


def test_bm25_ranks_relevant_chunk_first():
    # BM25 needs a non-trivial corpus before its IDF term becomes useful, so
    # we seed with a few unrelated chunks plus the relevant one.
    chunks = [
        Chunk(file="a.go", qualified_name="JSON.Bind", kind="method",
              start_line=1, end_line=10,
              code="func (j JSON) Bind(req *http.Request, obj any) error { return decodeJSON(req.Body, obj) }"),
        Chunk(file="b.go", qualified_name="add", kind="function",
              start_line=1, end_line=3, code="func add(a, b int) int { return a + b }"),
        Chunk(file="c.go", qualified_name="multiply", kind="function",
              start_line=1, end_line=3, code="func multiply(a, b int) int { return a * b }"),
        Chunk(file="d.go", qualified_name="sub", kind="function",
              start_line=1, end_line=3, code="func sub(a, b int) int { return a - b }"),
        Chunk(file="e.go", qualified_name="div", kind="function",
              start_line=1, end_line=3, code="func div(a, b int) int { return a / b }"),
    ]
    idx = BM25Index(chunks)
    hits = idx.query("JSON Bind request body decode", top_k=2)
    assert hits, "BM25 returned no hits"
    assert hits[0].chunk.qualified_name == "JSON.Bind"


def test_bm25_empty_query_returns_empty():
    chunks = [Chunk(file="a.go", qualified_name="x", kind="function",
                    start_line=1, end_line=1, code="x")]
    idx = BM25Index(chunks)
    assert idx.query("") == []
