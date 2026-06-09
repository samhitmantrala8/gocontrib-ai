"""Dense retrieval using sentence-transformers + ChromaDB.

Why local instead of Pinecone:
* Single-developer repo, no shared infra → a managed vector DB is overkill
  and adds an account/API-key burden the user shouldn't have to deal with.
* The Go repos in scope have ~3-15k symbols. ChromaDB's local persistent
  store handles that in well under a second per query on CPU.
* MiniLM-L6-v2 is 80MB, runs on CPU, and doesn't require a GPU or a network
  call at inference time — important when we're already calling out to
  Gemini for everything else.

If the user *does* want Pinecone (e.g. for a shared cache across team
members), the ``HybridRetriever`` accepts any object that exposes
``query(text, top_k) -> list[Hit]``."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from .bm25 import Hit
from .indexer import Chunk


def _stable_id(c: Chunk) -> str:
    h = hashlib.sha1(f"{c.file}::{c.qualified_name}::{c.start_line}".encode()).hexdigest()
    return h[:24]


class DenseIndex:
    """Lazy: model + chroma client are built only when query() is first called.
    Building the index is also lazy — if it's already on disk we reuse it."""

    def __init__(
        self,
        repo_path: str,
        chunks: list[Chunk],
        *,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        persist_dir: str | None = None,
    ):
        self.repo_path = repo_path
        self.chunks = chunks
        self.model_name = model_name
        self.persist_dir = persist_dir or os.path.join(repo_path, ".gocontrib_chroma")
        self._collection = None
        self._model = None
        self._chunk_by_id: dict[str, Chunk] = {}

    def _ensure_built(self) -> None:
        if self._collection is not None:
            return
        from chromadb import PersistentClient
        from sentence_transformers import SentenceTransformer

        Path(self.persist_dir).mkdir(parents=True, exist_ok=True)
        client = PersistentClient(path=self.persist_dir)
        # Collection name encodes commit-ish state of the chunk list so we
        # don't reuse a stale index after the repo changes.
        sig = hashlib.sha1(
            ("|".join(f"{c.file}:{c.start_line}:{c.end_line}" for c in self.chunks)).encode()
        ).hexdigest()[:10]
        coll_name = f"gocontrib_{sig}"
        try:
            self._collection = client.get_collection(coll_name)
            for c in self.chunks:
                self._chunk_by_id[_stable_id(c)] = c
            self._model = SentenceTransformer(self.model_name)
            return
        except Exception:                                               # noqa: BLE001
            pass

        self._model = SentenceTransformer(self.model_name)
        self._collection = client.create_collection(coll_name)
        ids: list[str] = []
        docs: list[str] = []
        for c in self.chunks:
            cid = _stable_id(c)
            self._chunk_by_id[cid] = c
            ids.append(cid)
            docs.append(_embed_text(c))
        if ids:
            embs = self._model.encode(docs, batch_size=64, show_progress_bar=False).tolist()
            # Chroma chokes on huge single inserts; chunk them.
            for i in range(0, len(ids), 256):
                self._collection.add(
                    ids=ids[i : i + 256],
                    embeddings=embs[i : i + 256],
                    documents=docs[i : i + 256],
                )

    def query(self, text: str, top_k: int = 20) -> list[Hit]:
        if not self.chunks:
            return []
        self._ensure_built()
        emb = self._model.encode([text]).tolist()[0]                    # type: ignore[union-attr]
        res = self._collection.query(query_embeddings=[emb], n_results=top_k)   # type: ignore[union-attr]
        hits: list[Hit] = []
        if not res.get("ids") or not res["ids"][0]:
            return hits
        ids = res["ids"][0]
        # Chroma returns squared L2 distance by default; convert to a
        # similarity score so larger == better, like BM25.
        dists = res.get("distances", [[0.0] * len(ids)])[0]
        for cid, d in zip(ids, dists):
            chunk = self._chunk_by_id.get(cid)
            if chunk is None:
                continue
            score = 1.0 / (1.0 + float(d))
            hits.append(Hit(chunk=chunk, score=score))
        return hits


def _embed_text(c: Chunk) -> str:
    """Embedding text is the symbol name + file path + first ~1500 chars of code.
    Putting the qualified name first weights it strongly under MiniLM's
    averaging."""
    head = f"{c.qualified_name}\nfile: {c.file}\n"
    return head + c.code[:1500]
