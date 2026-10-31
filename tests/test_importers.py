from __future__ import annotations

import json
from pathlib import Path

import pytest

from ragnoz.importers import import_jsonl, write_jsonl
from ragnoz.schemas import QuestionTrace


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def test_import_jsonl_uses_question_id_when_present(tmp_path: Path):
    path = _write(tmp_path / "t.jsonl", [{"question_id": "Q1", "question": "Capital?", "answer": "Paris"}])
    traces = import_jsonl(path)
    assert traces[0].question_id == "Q1"


def test_import_jsonl_generates_id_from_line_number_when_question_id_missing(tmp_path: Path):
    path = _write(tmp_path / "t.jsonl", [{"question": "Capital?", "answer": "Paris"}])
    traces = import_jsonl(path)
    assert traces[0].question_id == "import-0001"


def test_import_jsonl_raises_when_both_question_id_and_question_missing(tmp_path: Path):
    path = _write(tmp_path / "t.jsonl", [{"answer": "Paris"}])
    with pytest.raises(ValueError, match="question_id veya question gerekli"):
        import_jsonl(path)


def test_import_jsonl_skips_blank_lines(tmp_path: Path):
    path = tmp_path / "t.jsonl"
    path.write_text('{"question_id": "Q1", "question": "A?"}\n\n   \n{"question_id": "Q2", "question": "B?"}\n', encoding="utf-8")
    traces = import_jsonl(path)
    assert [t.question_id for t in traces] == ["Q1", "Q2"]


def test_import_jsonl_candidates_accept_plain_strings(tmp_path: Path):
    path = _write(tmp_path / "t.jsonl", [{"question_id": "Q1", "question": "A?", "retrieved_chunks": ["doc text one", "doc text two"]}])
    traces = import_jsonl(path)
    assert [c.doc_id for c in traces[0].candidates] == ["unknown-0", "unknown-1"]
    assert traces[0].candidates[0].text == "doc text one"


def test_import_jsonl_candidates_skip_entries_that_are_neither_str_nor_dict(tmp_path: Path):
    path = _write(tmp_path / "t.jsonl", [{"question_id": "Q1", "question": "A?", "retrieved_chunks": ["kept", 42, None, {"doc_id": "d1"}]}])
    traces = import_jsonl(path)
    assert [c.doc_id for c in traces[0].candidates] == ["unknown-0", "d1"]


def test_import_jsonl_candidates_default_to_empty_when_not_a_list(tmp_path: Path):
    path = _write(tmp_path / "t.jsonl", [{"question_id": "Q1", "question": "A?", "retrieved_chunks": "not-a-list"}])
    traces = import_jsonl(path)
    assert traces[0].candidates == []


def test_import_jsonl_with_custom_mapping_file(tmp_path: Path):
    path = _write(tmp_path / "t.jsonl", [{"qid": "Q1", "q_text": "Capital?", "ans": {"body": "Paris"}}])
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps({
        "question_id": "qid", "question": "q_text", "answer": "ans", "answer_text": "body",
    }), encoding="utf-8")
    traces = import_jsonl(path, mapping_path)
    assert traces[0].question_id == "Q1"
    assert traces[0].answer is not None
    assert traces[0].answer.text == "Paris"


def test_import_jsonl_mapping_resolves_nested_list_index_path(tmp_path: Path):
    path = _write(tmp_path / "t.jsonl", [{"id": "Q1", "nested": [{"text": "What is the capital?"}]}])
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps({"question_id": "id", "question": "nested.0.text"}), encoding="utf-8")
    traces = import_jsonl(path, mapping_path)
    assert traces[0].question == "What is the capital?"


def test_import_jsonl_mapping_list_index_out_of_range_falls_back_to_default(tmp_path: Path):
    path = _write(tmp_path / "t.jsonl", [{"id": "Q1", "question": "A?", "nested": [{"text": "only one"}]}])
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps({"question_id": "id", "answer": "nested.5.text"}), encoding="utf-8")
    traces = import_jsonl(path, mapping_path)
    assert traces[0].answer is not None
    assert traces[0].answer.text == ""


def test_write_jsonl_round_trips_through_import(tmp_path: Path):
    traces = [QuestionTrace(question_id="Q1", question="A?", route="answered")]
    out = tmp_path / "nested" / "out.jsonl"
    write_jsonl(traces, out)
    reread = import_jsonl(out)
    assert reread[0].question_id == "Q1"
