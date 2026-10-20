from __future__ import annotations

from ragnoz.compare import compare_evaluations
from ragnoz.evaluation import evaluate
from ragnoz.reports.html import render_html
from ragnoz.schemas import GoldenItem, QuestionTrace


def test_numeric_tolerance_ranges_and_units():
    tolerated = GoldenItem(id="N1", question="Height?", type="numeric", unit="m",
                          expected_values=[{"value": "8848.86", "tolerance": 0.1}])
    trace = QuestionTrace(question_id="N1", answer="The height is 8,848.90 m.")
    assert evaluate([tolerated], [trace])["items"][0]["correct"] is True

    ranged = GoldenItem(id="N2", question="Mass?", type="numeric", expected_min=3.0, expected_max=4.0, unit="kg")
    assert evaluate([ranged], [QuestionTrace(question_id="N2", answer="3.5 kg")])["items"][0]["correct"] is True
    assert evaluate([ranged], [QuestionTrace(question_id="N2", answer="5 kg")])["items"][0]["correct"] is False


def test_retrieval_metrics_use_answerable_denominator_and_rank_quality():
    item = GoldenItem(id="Q", question="Capital?", expected_answer="Paris",
                      evidence=[{"doc_id": "d", "quote": "Paris is the capital."}])
    trace = QuestionTrace(question_id="Q", answer="Paris", observability="L2",
        candidates=[{"doc_id": "noise", "text": "unrelated"}, {"doc_id": "d", "text": "Paris is the capital."}],
        ranked=[{"doc_id": "d", "text": "Paris is the capital."}, {"doc_id": "noise", "text": "unrelated"}])
    result = evaluate([item], [trace], ks=(2,))
    assert result["metrics"]["retrieval_n"] == 1
    assert result["metrics"]["hit@2"] == 1
    assert result["metrics"]["ndcg@2"] == 1
    assert result["metrics"]["candidate_ndcg@2"] < result["metrics"]["ndcg@2"]


def test_compare_includes_all_question_transitions_and_mcnemar():
    before = {"items": [{"question_id": "A", "correct": False, "attribution": "RETRIEVAL_MISS"},
                        {"question_id": "B", "correct": True, "attribution": "OK"}]}
    after = {"items": [{"question_id": "A", "correct": True, "attribution": "OK"},
                       {"question_id": "B", "correct": False, "attribution": "GEN_WRONG_OTHER"}]}
    result = compare_evaluations(before, after)
    assert len(result["question_transitions"]) == 2
    assert [row["transition"] for row in result["question_transitions"]] == ["fixed", "regressed"]
    assert result["mcnemar"]["p_value_exact"] == 1


def test_html_report_redacts_nested_credentials_and_has_no_remote_assets():
    evaluation = {"metrics": {"n": 1, "accuracy": 0.0},
                  "items": [{"question_id": "Q", "correct": False, "answer": "private@example.org", "reason": "token=do-not-leak"}]}
    diagnosis = {"profile": {"paradigm": "Naive", "modules": {"retrieval": {"api_key": "do-not-leak"}}}}
    report = render_html(evaluation, diagnosis, redact=True)
    assert "private@example.org" not in report
    assert "do-not-leak" not in report
    assert "<script src=" not in report
    assert "<link href=" not in report


def test_golden_quote_validation_normalizes_punctuation_and_unicode():
    from ragnoz.golden import validate_golden

    item = GoldenItem(id="C", question="Quote?", expected_answer="yes",
                      evidence=[{"doc_id": "w", "quote": "Charles Babbage's proposed mechanical computer"}])
    corpus = {"w": "Charles Babbage’s proposed mechanical, computer."}
    assert validate_golden([item], corpus) == []
