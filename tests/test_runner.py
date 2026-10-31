from __future__ import annotations

from pathlib import Path

from ragnoz.cache import StageCache
from ragnoz.runner import PipelineRunner
from ragnoz.schemas import GoldenItem


class FakeAdapter:
    def __init__(self, root: Path, answer: str = "Paris", fail: bool = False) -> None:
        self.root = root
        self.answer = answer
        self.fail = fail

    def load_documents(self):
        return [{"doc_id": "d1", "text": "Paris is the capital of France."}]

    def chunk(self, documents):
        return [{"doc_id": "d1", "page": 1, "text": documents[0]["text"]}]

    def index(self, chunks):
        return chunks

    def retrieve(self, question, index):
        if self.fail:
            raise RuntimeError("authorization=never-write-this-secret")
        return index

    def generate(self, question, context):
        return self.answer

    def describe(self):
        return {"system": "fake", "flow": "linear", "modules": {"retrieval": {"operator": "bm25"}}}

    def fingerprint(self, stage):
        return {"generate": self.answer if stage == "generate" else "stable"}


def item() -> GoldenItem:
    return GoldenItem(id="Q1", question="Capital of France?", expected_answer="Paris",
                      evidence=[{"doc_id": "d1", "quote": "Paris is the capital of France."}])


def test_generation_fingerprint_reuses_retrieval_stages(tmp_path):
    cache = StageCache(tmp_path / "cache")
    first = PipelineRunner(FakeAdapter(tmp_path, answer="Paris"), cache=cache).run([item()])
    assert first[0].answer.text == "Paris"
    before = cache.stats().copy()
    second = PipelineRunner(FakeAdapter(tmp_path, answer="London"), cache=cache).run([item()])
    after = cache.stats()
    assert second[0].answer.text == "London"
    assert after["hits"] - before["hits"] == 5  # chunk, index, retrieve, rerank, context
    assert after["misses"] - before["misses"] == 1  # generate only


def test_adapter_failure_does_not_persist_raw_secret(tmp_path):
    trace = PipelineRunner(FakeAdapter(tmp_path, fail=True), cache=StageCache(tmp_path / "cache")).run([item()])[0]
    assert trace.route == "error"
    assert trace.error is not None
    assert "never-write-this-secret" not in trace.error
    assert "authorization" not in trace.error
