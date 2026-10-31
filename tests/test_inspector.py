from __future__ import annotations

from pathlib import Path

import pytest

from ragnoz.inspector import (
    NotADraftError,
    draft_to_architecture,
    inspect_adapter_source,
    inspection_to_draft,
)

_ADAPTER_WITH_PATTERNS = '''
import faiss
from sentence_transformers import SentenceTransformer


class Adapter:
    def __init__(self):
        self.config = {"top_k": 7, "chunk_size": 256}

    def chunk(self, documents):
        return documents

    def rerank(self, question, candidates):
        return candidates

    def build_context(self, question, ranked):
        return ranked
'''

_ADAPTER_WITHOUT_PATTERNS = '''
class Adapter:
    def chunk(self, documents):
        return documents

    def retrieve(self, question, index):
        return index
'''


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "adapter.py"
    path.write_text(text, encoding="utf-8")
    return path


def test_inspect_adapter_source_finds_dict_literal_keys(tmp_path: Path):
    path = _write(tmp_path, _ADAPTER_WITH_PATTERNS)
    result = inspect_adapter_source(path)
    dict_findings = {(f.field, f.value): f for f in result.findings if f.pattern == "dict-literal-key"}
    assert ("top_k", "7") in dict_findings
    assert dict_findings[("top_k", "7")].module == "retrieval"
    assert ("chunk_size", "256") in dict_findings
    assert dict_findings[("chunk_size", "256")].module == "indexing.chunking"
    for f in result.findings:
        assert f.file == str(path)
        assert f.line > 0


def test_inspect_adapter_source_finds_imports(tmp_path: Path):
    path = _write(tmp_path, _ADAPTER_WITH_PATTERNS)
    result = inspect_adapter_source(path)
    imports = {f.value: f for f in result.findings if f.pattern == "import"}
    assert "faiss" in imports
    assert imports["faiss"].module == "indexing"
    assert "sentence_transformers" in imports
    assert imports["sentence_transformers"].module == "retrieval.embedding"


def test_inspect_adapter_source_finds_optional_method_presence(tmp_path: Path):
    path = _write(tmp_path, _ADAPTER_WITH_PATTERNS)
    result = inspect_adapter_source(path)
    methods = {f.value: f for f in result.findings if f.pattern == "method-def"}
    assert methods["rerank"].module == "post_retrieval.rerank"
    assert methods["build_context"].module == "post_retrieval.context"


def test_inspect_adapter_source_returns_no_findings_when_nothing_recognized(tmp_path: Path):
    path = _write(tmp_path, _ADAPTER_WITHOUT_PATTERNS)
    result = inspect_adapter_source(path)
    assert result.findings == []


def test_inspect_adapter_source_findings_are_sorted_by_line(tmp_path: Path):
    path = _write(tmp_path, _ADAPTER_WITH_PATTERNS)
    result = inspect_adapter_source(path)
    lines = [f.line for f in result.findings]
    assert lines == sorted(lines)


def test_inspection_to_draft_shape(tmp_path: Path):
    path = _write(tmp_path, _ADAPTER_WITH_PATTERNS)
    result = inspect_adapter_source(path)
    draft = inspection_to_draft(result, "2026-01-01T00:00:00+00:00")
    assert draft["inspected_draft"] is True
    assert draft["source_file"] == str(path)
    assert draft["inspected_utc"] == "2026-01-01T00:00:00+00:00"
    assert len(draft["findings"]) == len(result.findings)
    assert "approve" in draft["note"]
    for item in draft["findings"]:
        assert set(item) == {"module", "field", "value", "file", "line", "pattern"}


def test_draft_to_architecture_groups_findings_by_stage():
    draft = {
        "inspected_draft": True,
        "source_file": "adapter.py",
        "inspected_utc": "2026-01-01T00:00:00+00:00",
        "findings": [
            {"module": "indexing.chunking", "field": "chunk_size", "value": "256", "file": "adapter.py", "line": 1, "pattern": "dict-literal-key"},
            {"module": "retrieval", "field": "top_k", "value": "7", "file": "adapter.py", "line": 2, "pattern": "dict-literal-key"},
            {"module": "post_retrieval.rerank", "field": "method_present", "value": "rerank", "file": "adapter.py", "line": 3, "pattern": "method-def"},
            {"module": "generation", "field": "generator", "value": "extractive", "file": "adapter.py", "line": 4, "pattern": "dict-literal-key"},
        ],
    }
    architecture = draft_to_architecture(draft)
    assert architecture["modules"]["indexing"]["chunking"]["chunk_size"] == "256"
    assert architecture["modules"]["retrieval"]["retriever"]["top_k"] == "7"
    assert architecture["modules"]["post_retrieval"]["reranker"]["method_present"] == "rerank"
    assert architecture["modules"]["generation"]["generator"]["generator"] == "extractive"
    assert architecture["inspected_source"] == "adapter.py"


def test_draft_to_architecture_rejects_non_draft_input():
    with pytest.raises(NotADraftError):
        draft_to_architecture({"modules": {"retrieval": {}}})


def test_inspect_adapter_source_ignores_unmapped_and_non_literal_entries(tmp_path: Path):
    text = '''
import os


class Adapter:
    def __init__(self):
        self.config = {"top_k": self.other_value, "unrelated_key": "x", 1: "numeric key ignored"}
'''
    path = _write(tmp_path, text)
    result = inspect_adapter_source(path)
    assert not any(f.pattern == "import" for f in result.findings)  # os is not a known RAG library
    assert not any(f.field == "unrelated_key" for f in result.findings)
    top_k_findings = [f for f in result.findings if f.field == "top_k"]
    assert len(top_k_findings) == 1
    assert top_k_findings[0].value == "self.other_value"  # ast.literal_eval fails -> unparse fallback


def test_draft_to_architecture_unknown_module_falls_back_to_value_subkey():
    draft = {"inspected_draft": True, "findings": [
        {"module": "something_unmapped", "field": "field_x", "value": "v", "file": "a.py", "line": 1, "pattern": "dict-literal-key"},
    ]}
    architecture = draft_to_architecture(draft)
    assert architecture["modules"]["something_unmapped"]["value"]["field_x"] == "v"
