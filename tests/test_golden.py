from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ragnoz.golden import golden_hash, load_corpus_json, load_golden, validate_golden
from ragnoz.schemas import GoldenItem


def _item(**overrides: object) -> GoldenItem:
    base = {"id": "Q1", "question": "What?", "expected_answer": "A"}
    base.update(overrides)
    return GoldenItem(**base)


def test_load_golden_reads_jsonl(tmp_path: Path):
    path = tmp_path / "golden.jsonl"
    path.write_text(json.dumps({"id": "Q1", "question": "Capital?", "expected_answer": "Paris"}) + "\n", encoding="utf-8")
    items = load_golden(path)
    assert len(items) == 1
    assert items[0].id == "Q1"


def test_load_golden_reads_yaml_bare_list(tmp_path: Path):
    path = tmp_path / "golden.yaml"
    path.write_text(yaml.safe_dump([{"id": "Q1", "question": "Capital?", "expected_answer": "Paris"}]), encoding="utf-8")
    items = load_golden(path)
    assert len(items) == 1


def test_load_golden_reads_yaml_items_key(tmp_path: Path):
    path = tmp_path / "golden.yaml"
    path.write_text(yaml.safe_dump({"items": [{"id": "Q1", "question": "Capital?", "expected_answer": "Paris"}]}), encoding="utf-8")
    items = load_golden(path)
    assert len(items) == 1


def test_load_golden_reads_yaml_questions_key(tmp_path: Path):
    path = tmp_path / "golden.yaml"
    path.write_text(yaml.safe_dump({"questions": [{"id": "Q1", "question": "Capital?", "expected_answer": "Paris"}]}), encoding="utf-8")
    items = load_golden(path)
    assert len(items) == 1


def test_load_golden_rejects_non_list_payload(tmp_path: Path):
    path = tmp_path / "golden.yaml"
    path.write_text(yaml.safe_dump({"items": "not-a-list"}), encoding="utf-8")
    with pytest.raises(TypeError):
        load_golden(path)


def test_golden_hash_is_stable_and_order_sensitive_to_content():
    items_a = [_item(id="Q1"), _item(id="Q2")]
    items_b = [_item(id="Q1"), _item(id="Q2")]
    items_c = [_item(id="Q1"), _item(id="Q3")]
    assert golden_hash(items_a) == golden_hash(items_b)
    assert golden_hash(items_a) != golden_hash(items_c)


def test_validate_golden_flags_duplicate_ids():
    issues = validate_golden([_item(id="Q1"), _item(id="Q1")])
    assert any("yinelenen ID" in issue for issue in issues)


def test_validate_golden_flags_missing_answer_for_answer_behavior():
    item = _item(expected_answer=None, expected_values=[])
    issues = validate_golden([item])
    assert any("expected_answer/expected_values eksik" in issue for issue in issues)


def test_validate_golden_flags_missing_clarify_options():
    item = _item(expected_behavior="clarify", clarify_options=[])
    issues = validate_golden([item])
    assert any("clarify_options boş" in issue for issue in issues)


def test_validate_golden_skips_evidence_checks_without_corpus():
    item = _item(evidence=[{"doc_id": "missing-doc", "quote": "anything"}])
    assert validate_golden([item], corpus=None) == []


def test_validate_golden_flags_doc_id_not_in_corpus():
    item = _item(evidence=[{"doc_id": "missing-doc", "quote": "anything"}])
    issues = validate_golden([item], corpus={"other-doc": "some text"})
    assert any("korpusta olmayan doc_id" in issue for issue in issues)


def test_validate_golden_accepts_exact_quote_match():
    item = _item(evidence=[{"doc_id": "d1", "quote": "Paris is the capital"}])
    issues = validate_golden([item], corpus={"d1": "Everyone agrees Paris is the capital of France."})
    assert issues == []


def test_validate_golden_accepts_fuzzy_quote_match_within_threshold():
    item = _item(evidence=[{"doc_id": "d1", "quote": "Paris is the capitol"}])  # one-letter typo
    issues = validate_golden([item], corpus={"d1": "Everyone agrees Paris is the capital of France."})
    assert issues == []


def test_validate_golden_flags_quote_with_no_fuzzy_match():
    item = _item(evidence=[{"doc_id": "d1", "quote": "completely unrelated text about spacecraft"}])
    issues = validate_golden([item], corpus={"d1": "Everyone agrees Paris is the capital of France."})
    assert any("kanıt alıntısı bulunamadı" in issue for issue in issues)


def test_validate_golden_flags_evidence_with_no_position_info():
    item = _item(evidence=[{"doc_id": "d1"}])
    issues = validate_golden([item], corpus={"d1": "some text"})
    assert any("sayfa/aralık/alinti konumu belirtilmemiş" in issue for issue in issues)


def test_load_corpus_json_dict_format(tmp_path: Path):
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps({"d1": "text one"}), encoding="utf-8")
    assert load_corpus_json(path) == {"d1": "text one"}


def test_load_corpus_json_list_format_with_doc_id(tmp_path: Path):
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps([{"doc_id": "d1", "text": "text one"}]), encoding="utf-8")
    assert load_corpus_json(path) == {"d1": "text one"}


def test_load_corpus_json_list_format_falls_back_to_pageid_and_extract(tmp_path: Path):
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps([{"pageid": "42", "extract": "extracted text"}]), encoding="utf-8")
    assert load_corpus_json(path) == {"42": "extracted text"}
