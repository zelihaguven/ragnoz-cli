from __future__ import annotations

from ragnoz.diagnosis import diagnose
from ragnoz.diagnosis.engine import discover_architecture
from ragnoz.schemas import GoldenItem, ItemEvaluation, QuestionTrace


def test_core_rule_branches_require_measured_evidence_and_ablation_pairs():
    items: list[GoldenItem] = []
    traces: list[QuestionTrace] = []
    evaluations: list[ItemEvaluation] = []

    def add(item_id: str, question_type: str, attribution: str, candidate: bool, in_context: bool, lang: str = "en"):
        item = GoldenItem(id=item_id, question=f"Question {item_id}?", lang=lang, type=question_type,
                          tags=["exact_id"] if question_type == "exact_id" else [],
                          expected_values=[100] if question_type == "numeric" else [],
                          expected_answer="expected" if question_type != "numeric" else None,
                          evidence=[{"doc_id": f"doc-{item_id}", "quote": f"evidence {item_id}"}])
        items.append(item)
        chunk_doc = f"doc-{item_id}" if candidate else "wrong"
        chunk = {"doc_id": chunk_doc, "text": f"evidence {item_id}" if candidate else "irrelevant"}
        context = [chunk] if in_context else []
        traces.append(QuestionTrace(question_id=item_id, question=item.question, route_label="route-a" if len(items) % 2 else "route-b",
                                    candidates=[chunk], ranked=[chunk], context=context, observability="L3"))
        evaluations.append(ItemEvaluation(question_id=item_id, correct=False, evidence_in_candidates=candidate,
                                          evidence_in_ranked=candidate, evidence_in_context=in_context,
                                          attribution=attribution))

    for index in range(3):
        add(f"N{index}", "numeric", "GEN_NUMBER_EXTRACTION", True, True)
    for index in range(5):
        add(f"C{index}", "factual", "CHUNK_BOUNDARY", True, False)
    for index in range(3):
        add(f"X{index}", "exact_id", "RETRIEVAL_MISS", False, False)

    architecture = {
        "context_window_tokens": 2048,
        "top_k": 4,
        "modules": {
            "pre_retrieval": {"query_rewrite": True},
            "indexing": {"chunking": {"size_tokens": 600}},
            "retrieval": {"top_k": 4, "retriever": {"operator": "dense", "operators": ["dense"]}},
        },
    }
    ablations = {
        "remove": {"passed": True, "module": "reranker", "accuracy_delta_ci95": [-0.01, 0.02],
                   "latency_cost_delta": 0.25},
        "oracle_context": {"accuracy_delta": 0.0},
        "no_context": {"accuracy_delta": 0.0},
    }
    result = diagnose(items, traces, evaluations, architecture, ablations=ablations)
    found = {finding["id"] for finding in result["findings"]}
    assert {"AP-01", "AP-02", "AP-03", "AP-08", "AP-12", "AP-13", "AP-18"}.issubset(found)
    assert result["profile"]["flow"] == "conditional"
    assert result["profile"]["paradigm"] == "Modular"
    assert all(rec["confidence"] != "high" for rec in result["recommendations"])


def test_architecture_loop_inference_declaration_mismatch_and_unknown_profile():
    traces = [QuestionTrace(question_id="A", retrieval_rounds=2, candidates=[{"doc_id": "d", "text": "x"}],
                           ranked=[{"doc_id": "d", "text": "x"}], observability="L2")]
    profile = discover_architecture(traces, {"modules": {"post_retrieval": "cross-encoder"}})
    assert profile.flow == "loop"
    assert profile.paradigm == "Modular"
    assert profile.mismatches
    assert profile.facts[0]["source"] == "declaration"
    assert discover_architecture([], {}).paradigm == "Undetermined"
