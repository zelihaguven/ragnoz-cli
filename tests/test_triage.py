from __future__ import annotations

import pytest
from pydantic import ValidationError

from ragnoz.diagnosis import (
    diagnose,
    filter_diagnosis_by_complaint,
    guidance_for_complaint,
    match_symptoms,
)
from ragnoz.schemas import GoldenItem, Guidance, ItemEvaluation, QuestionTrace


def test_guidance_type_rejects_fix_or_confidence_fields():
    with pytest.raises(ValidationError):
        Guidance(symptom="x", module="m", next_command="y", change="do this")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Guidance(symptom="x", module="m", next_command="y", confidence="high")  # type: ignore[call-arg]


def test_match_symptoms_finds_known_keywords_case_insensitively():
    assert "irrelevant_answer" in match_symptoms("Cevaplar ALAKASIZ geliyor")
    assert "wrong_number" in match_symptoms("sayı hep yanlış çıkıyor")
    assert match_symptoms("bugün hava çok güzel, dışarı çıkalım mı") == []


def test_guidance_for_complaint_points_to_module_and_rules_without_fix_text():
    guidance = guidance_for_complaint("Cevaplar alakasız geliyor")
    assert guidance
    item = guidance[0]
    assert "AP-" in ",".join(item.rule_ids) or item.rule_ids
    assert item.module
    assert "golden quickstart" in item.next_command
    assert not hasattr(item, "change")
    assert not hasattr(item, "hypothesis")


def test_guidance_next_command_switches_when_golden_already_exists():
    without = guidance_for_complaint("sayı hep yanlış çıkıyor", has_golden=False)
    with_golden = guidance_for_complaint("sayı hep yanlış çıkıyor", has_golden=True)
    assert "quickstart" in without[0].next_command
    assert "ragnoz run" in with_golden[0].next_command


def test_unrecognized_complaint_returns_no_guidance():
    assert guidance_for_complaint("bugün hava çok güzel") == []


def test_filter_diagnosis_by_complaint_narrows_to_matching_rules_only():
    items = [GoldenItem(id="N0", question="Kaç?", type="numeric", expected_values=[100],
                        evidence=[{"doc_id": "d", "quote": "100"}])]
    chunk = {"doc_id": "d", "text": "100"}
    traces = [QuestionTrace(question_id="N0", candidates=[chunk], ranked=[chunk], context=[chunk], observability="L3")]
    evaluations = [ItemEvaluation(question_id="N0", correct=False, evidence_in_candidates=True,
                                  evidence_in_ranked=True, evidence_in_context=True, attribution="GEN_NUMBER_EXTRACTION")]
    for _ in range(2):
        items.append(GoldenItem(id=f"N{_+1}", question="Kaç?", type="numeric", expected_values=[100],
                                evidence=[{"doc_id": "d", "quote": "100"}]))
        traces.append(QuestionTrace(question_id=f"N{_+1}", candidates=[chunk], ranked=[chunk], context=[chunk], observability="L3"))
        evaluations.append(ItemEvaluation(question_id=f"N{_+1}", correct=False, evidence_in_candidates=True,
                                          evidence_in_ranked=True, evidence_in_context=True, attribution="GEN_NUMBER_EXTRACTION"))

    result = diagnose(items, traces, evaluations)
    assert {f["id"] for f in result["findings"]} == {"AP-12"}

    filtered = filter_diagnosis_by_complaint("sayı hep yanlış çıkıyor", result)
    assert filtered["matched_symptoms"] == ["wrong_number"]
    assert {f["id"] for f in filtered["findings"]} == {"AP-12"}

    unrelated = filter_diagnosis_by_complaint("cevap çok yavaş geliyor", result)
    assert unrelated["findings"] == []
    assert unrelated["recommendations"] == []
