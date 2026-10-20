from __future__ import annotations

from ragnoz.demo import build_demo_traces, demo_path, load_demo_items
from ragnoz.diagnosis import diagnose
from ragnoz.evaluation import evaluate
from ragnoz.schemas import GoldenItem, ItemEvaluation, QuestionTrace


def test_wiki_demo_shape_and_abstention_count():
    items = load_demo_items()
    assert len(items) == 40
    assert sum(item.expected_behavior == "abstain" for item in items) >= 8
    assert (demo_path() / "wiki-mini.revisions.json").exists()


def test_broken_reference_pipeline_has_evidence_backed_core_findings():
    items = load_demo_items()
    traces = build_demo_traces("broken", items)
    evaluated = evaluate(items, traces)
    profile = __import__("yaml").safe_load((demo_path() / "pipelines" / "broken.yaml").read_text())
    result = diagnose(items, traces, [ItemEvaluation(**row) for row in evaluated["items"]], profile)
    found = {row["id"] for row in result["findings"]}
    assert {"AP-01", "AP-04", "AP-05", "AP-07"}.issubset(found)
    assert all(row["confidence"] in {"low", "medium"} for row in result["recommendations"])
    assert result["profile"]["paradigm"] == "Naive"
    assert "kalite sıralaması değildir" in result["profile"]["taxonomy_note"]


def test_abstain_recall_uses_only_gold_abstention_items():
    items = [
        GoldenItem(id="U", question="Unsupported?", type="unanswerable", expected_behavior="abstain"),
        GoldenItem(id="F", question="Supported?", expected_answer="yes"),
    ]
    traces = [QuestionTrace(question_id="U", answer="guessed"),
              QuestionTrace(question_id="F", answer="yes")]
    metrics = evaluate(items, traces)["metrics"]
    assert metrics["abstain_n"] == 1
    assert metrics["abstain_recall"] == 0
    assert metrics["abstain_precision"] is None


def test_all_evidence_mode_requires_every_quote():
    item = GoldenItem(id="M", question="Two facts?", expected_answer="alpha beta", evidence_mode="all",
                      evidence=[{"doc_id": "d", "quote": "alpha"}, {"doc_id": "d", "quote": "beta"}])
    trace = QuestionTrace(question_id="M", answer="alpha beta", observability="L1",
                          context=[{"doc_id": "d", "text": "alpha only"}])
    result = evaluate(items=[item], traces=[trace])["items"][0]
    assert result["evidence_in_context"] is False
