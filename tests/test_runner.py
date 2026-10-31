from __future__ import annotations

from pathlib import Path

import pytest

from ragnoz.adapters.base import AdapterError
from ragnoz.cache import StageCache
from ragnoz.runner import PipelineRunner, _jsonable
from ragnoz.schemas import GoldenItem, QuestionTrace


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


class NoFingerprintAdapter:
    """Adapter without a custom `fingerprint` method, to exercise the runner's fallback."""

    def __init__(self) -> None:
        self.config = {"k": 1}

    def load_documents(self):
        return [{"doc_id": "d1", "text": "Paris is the capital of France."}]

    def chunk(self, documents):
        return documents

    def index(self, chunks):
        return chunks

    def retrieve(self, question, index):
        return index

    def generate(self, question, context):
        return "Paris"


class ChunkFailsAdapter(NoFingerprintAdapter):
    def chunk(self, documents):
        raise RuntimeError("chunk stage boom")


class LoadDocumentsFailsAdapter(NoFingerprintAdapter):
    def load_documents(self):
        raise RuntimeError("load_documents boom")


def test_fingerprint_falls_back_to_source_hash_without_custom_method(tmp_path):
    runner = PipelineRunner(NoFingerprintAdapter(), cache=StageCache(tmp_path / "cache"))
    fingerprint = runner._fingerprint("chunk")
    assert fingerprint["stage"] == "chunk"
    assert "method_source_sha256" in fingerprint
    assert fingerprint["config"] == {"k": 1}


def test_fingerprint_fallback_handles_unreadable_source(tmp_path):
    adapter = NoFingerprintAdapter()
    adapter.builtin_stage = len  # a builtin has no retrievable Python source
    runner = PipelineRunner(adapter, cache=StageCache(tmp_path / "cache"))
    fingerprint = runner._fingerprint("builtin_stage")
    assert fingerprint["stage"] == "builtin_stage"


def test_jsonable_handles_pydantic_models_and_tuples():
    trace = QuestionTrace(question_id="Q1", question="A?")
    assert _jsonable(trace)["question_id"] == "Q1"
    assert _jsonable((1, 2, 3)) == [1, 2, 3]


def test_no_cache_skips_both_cache_read_and_write(tmp_path):
    cache = StageCache(tmp_path / "cache")
    PipelineRunner(FakeAdapter(tmp_path), cache=cache, no_cache=True).run([item()])
    stats = cache.stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 0


def test_document_loading_stage_failure_propagates_as_adapter_error_without_wrapping_again(tmp_path):
    runner = PipelineRunner(ChunkFailsAdapter(), cache=StageCache(tmp_path / "cache"))
    with pytest.raises(AdapterError, match="chunk"):
        runner.run([item()])


def test_raw_load_documents_failure_is_wrapped_as_adapter_error(tmp_path):
    runner = PipelineRunner(LoadDocumentsFailsAdapter(), cache=StageCache(tmp_path / "cache"))
    with pytest.raises(AdapterError, match="Doküman yükleme"):
        runner.run([item()])
