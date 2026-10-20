from __future__ import annotations

import re
from pathlib import Path


class WikiMiniAdapter:
    """Small CPU-only token-overlap/extractive adapter for the pinned wiki-mini corpus."""

    def __init__(self, corpus_path: str | Path = ".ragnoz/demo-corpus/pages.json") -> None:
        self.corpus_path = Path(corpus_path)
        self.config = {"top_k": 5, "retriever": "token-overlap-v1", "generator": "extractive"}

    def load_documents(self):
        import json
        if not self.corpus_path.exists():
            raise FileNotFoundError("Demo corpus yok; önce `ragnoz demo init` çalıştırın.")
        pages = json.loads(self.corpus_path.read_text(encoding="utf-8"))
        return [{"doc_id": page["doc_id"], "title": page["title"], "text": page["text"]} for page in pages]

    def chunk(self, documents):
        chunks = []
        for document in documents:
            for index, paragraph in enumerate(re.split(r"(?<=[.!?])\s+", document["text"])):
                text = paragraph.strip()
                if text:
                    chunks.append({"chunk_id": f"{document['doc_id']}:{index}", "doc_id": document["doc_id"],
                                   "page": 1, "text": text})
        return chunks

    def index(self, chunks):
        return chunks

    @staticmethod
    def _tokens(text):
        return {token for token in re.findall(r"[\w]+", text.casefold()) if len(token) > 2}

    def retrieve(self, question, index):
        query_tokens = self._tokens(question)
        scored = []
        for chunk in index:
            tokens = self._tokens(chunk["text"])
            score = len(query_tokens & tokens) / max(1, len(query_tokens))
            if score:
                scored.append({**chunk, "score": score})
        scored.sort(key=lambda row: (-row["score"], row["chunk_id"]))
        for rank, row in enumerate(scored[: self.config["top_k"]], 1):
            row["rank"] = rank
        return scored[: self.config["top_k"]]

    def generate(self, question, context):
        if not context:
            return {"text": "", "abstained": True}
        return {"text": context[0]["text"], "abstained": False}

    def describe(self):
        return {"system": "wiki-mini-naive", "flow": "linear", "modules": {
            "indexing": {"chunking": {"operator": "sentence"}},
            "retrieval": {"retriever": {"operator": "token_overlap", "top_k": self.config["top_k"]}},
            "generation": {"generator": {"operator": "extractive", "abstention": "empty-context"}},
        }, "context_window_tokens": 8192}

    def fingerprint(self, stage):
        return {"adapter": "wiki-mini-token-overlap-v1", "stage": stage,
                "config": self.config if stage in {"retrieve", "generate"} else {"version": "1"}}


def build_demo_adapter():
    return WikiMiniAdapter()
