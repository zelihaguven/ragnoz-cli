from __future__ import annotations

from ragnoz.golden import validate_golden
from ragnoz.golden_quickstart import build_golden_items, detect_format


def test_csv_happy_path_assigns_ids_and_infers_answer_behavior():
    text = "question,answer\nCapital of France?,Paris\nCapital of Japan?,Tokyo\n"
    result = build_golden_items(text, "csv")
    assert not result.errors
    assert [item.id for item in result.items] == ["q-001", "q-002"]
    assert [item.expected_answer for item in result.items] == ["Paris", "Tokyo"]
    assert all(item.expected_behavior == "answer" for item in result.items)


def test_csv_blank_answer_infers_abstain_behavior():
    text = "question,answer\nWho won the 2099 election?,\n"
    result = build_golden_items(text, "csv")
    assert not result.errors
    assert result.items[0].expected_behavior == "abstain"
    assert result.items[0].expected_answer is None


def test_csv_row_with_empty_question_is_skipped_with_line_numbered_error():
    text = "question,answer\nCapital of France?,Paris\n,Should be skipped\nCapital of Japan?,Tokyo\n"
    result = build_golden_items(text, "csv")
    assert [item.question for item in result.items] == ["Capital of France?", "Capital of Japan?"]
    assert len(result.errors) == 1
    assert result.errors[0].startswith("satır 3:")
    assert "question" in result.errors[0]


def test_csv_explicit_id_does_not_collide_with_generated_id():
    text = "id,question,answer\nq-002,First?,A\n,Second?,B\n"
    result = build_golden_items(text, "csv")
    assert not result.errors
    assert [item.id for item in result.items] == ["q-002", "q-003"]


def test_jsonl_malformed_line_reports_line_number_and_keeps_valid_rows():
    text = '{"question": "Q1?", "answer": "A1"}\n{not valid json}\n{"question": "Q2?", "answer": "A2", "id": "custom-1"}\n'
    result = build_golden_items(text, "jsonl")
    assert [item.id for item in result.items] == ["q-001", "custom-1"]
    assert len(result.errors) == 1
    assert result.errors[0].startswith("satır 2:")


def test_markdown_table_happy_path():
    text = "| question | answer |\n| --- | --- |\n| Capital of France? | Paris |\n| Capital of Japan? | Tokyo |\n"
    result = build_golden_items(text, "markdown")
    assert not result.errors
    assert [item.expected_answer for item in result.items] == ["Paris", "Tokyo"]


def test_detect_format_sniffs_csv_jsonl_and_markdown():
    assert detect_format("question,answer\nA?,B\n") == "csv"
    assert detect_format('{"question": "A?", "answer": "B"}\n') == "jsonl"
    assert detect_format("| question | answer |\n| --- | --- |\n") == "markdown"
    assert detect_format("anything", suffix=".csv") == "csv"
    assert detect_format("anything", suffix=".jsonl") == "jsonl"
    assert detect_format("anything", suffix=".md") == "markdown"


def test_evidence_and_tags_columns_round_trip_into_golden_item():
    text = "question,answer,tags,evidence_doc_id,evidence_quote\nQ1?,A1,numeric|hard,doc-1,exact quote\n"
    result = build_golden_items(text, "csv")
    assert not result.errors
    item = result.items[0]
    assert item.tags == ["numeric", "hard"]
    assert item.evidence[0].doc_id == "doc-1"
    assert item.evidence[0].quote == "exact quote"


def test_jsonl_non_object_line_reports_line_numbered_error():
    text = '["not", "an", "object"]\n{"question": "Q1?", "answer": "A1"}\n'
    result = build_golden_items(text, "jsonl")
    assert [item.id for item in result.items] == ["q-002"]
    assert result.errors == ["satır 1: JSON nesnesi (obje) bekleniyor"]


def test_empty_input_produces_no_items_and_no_errors():
    result = build_golden_items("", "csv")
    assert result.items == []
    assert result.errors == []


def test_quickstart_output_feeds_directly_into_existing_validate_golden():
    text = "id,question,answer\nq-1,First?,A\nq-1,Second?,B\n"
    result = build_golden_items(text, "csv")
    assert not result.errors
    issues = validate_golden(result.items)
    assert any("yinelenen ID" in issue for issue in issues)
