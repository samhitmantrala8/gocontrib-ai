from go_contributor.rag.bm25 import BM25Index
from go_contributor.rag.hybrid import HybridConfig, HybridRetriever
from go_contributor.rag.indexer import Chunk


def _chunks():
    return [
        Chunk(file="binding/json.go", qualified_name="decodeJSON", kind="function",
              start_line=1, end_line=20,
              code="func decodeJSON(r io.Reader, obj any) error { return nil }"),
        Chunk(file="binding/json.go", qualified_name="JSON.Bind", kind="method",
              start_line=22, end_line=40,
              code="func (j JSON) Bind(req *http.Request, obj any) error { return decodeJSON(req.Body, obj) }"),
        Chunk(file="render/json.go", qualified_name="encodeJSON", kind="function",
              start_line=1, end_line=10,
              code="func encodeJSON(w io.Writer, obj any) error { return nil }"),
    ]


def test_graph_expansion_pulls_callees():
    chunks = _chunks()
    # JSON.Bind calls decodeJSON
    graph = {
        "JSON.Bind": {"decodeJSON"},
        "decodeJSON": set(),
        "encodeJSON": set(),
    }
    bm25 = BM25Index(chunks)
    retriever = HybridRetriever(
        chunks=chunks,
        symbol_graph=graph,
        bm25=bm25,
        dense=None,
        cfg=HybridConfig(bm25_weight=0.7, dense_weight=0.0, graph_weight=1.0, top_k=3),
    )
    out = retriever.query("JSON Bind")
    names = [c.qualified_name for c in out]
    # Bind should rank first lexically; decodeJSON should also be present via graph hop.
    assert "JSON.Bind" in names
    assert "decodeJSON" in names


def test_no_dense_does_not_crash():
    chunks = _chunks()
    retriever = HybridRetriever(
        chunks=chunks,
        symbol_graph={"decodeJSON": set(), "JSON.Bind": set(), "encodeJSON": set()},
        bm25=BM25Index(chunks),
        dense=None,
        cfg=HybridConfig(bm25_weight=1.0, dense_weight=0.0, graph_weight=0.0, top_k=2),
    )
    out = retriever.query("encode")
    assert any(c.qualified_name == "encodeJSON" for c in out)
