from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any

from ragnoz.schemas import GoldenItem, ItemEvaluation, QuestionTrace, ScoredChunk
from ragnoz.statistics import wilson_ci


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _chunk_has_evidence(chunk: ScoredChunk, item: GoldenItem) -> bool:
    return any(_chunk_matches(chunk, evidence) for evidence in item.evidence)


def _chunk_matches(chunk: ScoredChunk, evidence: Any) -> bool:
    if chunk.doc_id != evidence.doc_id:
        return False
    if evidence.page is not None and chunk.page is not None and str(evidence.page) != str(chunk.page):
        return False
    if evidence.quote and evidence.quote.casefold() not in chunk.text.casefold():
        if evidence.char_start is None or evidence.char_end is None:
            return False
        if not (chunk.char_start is not None and chunk.char_end is not None and
                chunk.char_start <= evidence.char_start < chunk.char_end):
            return False
    return True


def _list_has_evidence(chunks: list[ScoredChunk], item: GoldenItem) -> bool | None:
    if not chunks:
        return None
    found = [any(_chunk_matches(chunk, evidence) for chunk in chunks) for evidence in item.evidence]
    if not found:
        return False
    return all(found) if item.evidence_mode == "all" else any(found)


def _numbers(text: str) -> list[str]:
    matches = re.findall(r"(?<!\w)[+-]?\d+(?:[.,]\d+)*", text)
    normalized = []
    for match in matches:
        value = re.sub(r"\s", "", match)
        if "," in value and "." in value:
            value = value.replace(",", "")
        elif "," in value:
            tail = value.rsplit(",", 1)[-1]
            value = value.replace(",", "" if len(tail) == 3 else ".")
        normalized.append(value)
    return normalized


def _float_numbers(text: str) -> list[float]:
    values: list[float] = []
    for value in _numbers(text):
        try:
            values.append(float(value))
        except ValueError:
            continue
    return values


def _is_correct(item: GoldenItem, text: str, abstained: bool, route: str, choices: list[str]) -> tuple[bool | None, str]:
    if item.expected_behavior == "abstain":
        return (abstained or route == "abstained", "Beklenen davranış reddetmeydi." if not (abstained or route == "abstained") else "Beklenen reddetme gerçekleşti.")
    if item.expected_behavior == "clarify":
        got = {normalize_text(x) for x in choices}
        wanted = {normalize_text(x) for x in item.clarify_options}
        ok = route == "clarified" and wanted.issubset(got)
        return ok, "Netleştirme seçenekleri eşleşti." if ok else "Netleştirme davranışı/seçenekleri beklenenle uyuşmadı."
    if abstained or route in {"abstained", "clarified"}:
        return False, "Yanıt beklenirken sistem reddetti veya netleştirme istedi."
    norm = normalize_text(text)
    if item.expected_answer:
        expected = normalize_text(item.expected_answer)
        if (expected == norm or expected in norm) and all(normalize_text(x) in norm for x in item.must_include) and not any(normalize_text(x) in norm for x in item.must_not_include):
            return True, "Normalize cevap beklenen yanıtı ve içerik kısıtlarını karşıladı."
    if item.expected_values:
        actual_numbers = _float_numbers(text)
        expected_numbers: list[tuple[float | None, float, bool]] = []
        for expected_value in item.expected_values:
            raw_value = expected_value.get("value") if isinstance(expected_value, dict) else expected_value
            try:
                parsed = _numbers(str(raw_value))
                if not parsed:
                    raise ValueError("expected value is not numeric")
                expected_number = float(parsed[0])
            except (TypeError, ValueError):
                expected_numbers.append((None, 0.0, str(raw_value) in text or normalize_text(str(raw_value)) in norm))
                continue
            tolerance = float(expected_value.get("tolerance", item.numeric_tolerance)) if isinstance(expected_value, dict) else item.numeric_tolerance
            expected_numbers.append((expected_number, max(0.0, tolerance), False))
        matched = [
            (any(abs(actual - expected) <= tolerance for actual in actual_numbers)
             if expected is not None else text_match)
            for expected, tolerance, text_match in expected_numbers
        ]
        values_match = all(matched) if item.expected_values_mode == "all" else any(matched)
        unit_match = not item.unit or normalize_text(item.unit) in norm
        if values_match and unit_match:
            return True, "Beklenen sayısal değer tolerans/aralık kuralıyla bulundu."
    if item.expected_min is not None or item.expected_max is not None:
        actual_numbers = _float_numbers(text)
        in_range = [
            (item.expected_min is None or value >= item.expected_min - item.numeric_tolerance)
            and (item.expected_max is None or value <= item.expected_max + item.numeric_tolerance)
            for value in actual_numbers
        ]
        if any(in_range) and (not item.unit or normalize_text(item.unit) in norm):
            return True, "Yanıt beklenen sayısal aralık ve birimle eşleşti."
    if item.must_include and all(normalize_text(x) in norm for x in item.must_include) and not any(normalize_text(x) in norm for x in item.must_not_include):
        return True, "Zorunlu ifadeler bulundu ve yasaklı ifadeler yok."
    return False, "Cevap beklenen içerikle eşleşmedi."


def evaluate_item(item: GoldenItem, trace: QuestionTrace) -> ItemEvaluation:
    answer = trace.answer.text if trace.answer else ""
    abstained = trace.answer.abstained if trace.answer else False
    choices = trace.answer.clarify_options if trace.answer else []
    ev_cand = _list_has_evidence(trace.candidates, item)
    ev_rank = _list_has_evidence(trace.ranked, item)
    ev_ctx = _list_has_evidence(trace.context, item)
    correct, reason = _is_correct(item, answer, abstained, trace.route, choices)

    if trace.route == "error" or trace.answer is None:
        attribution = "SYS_ERROR"
    elif item.expected_behavior == "abstain":
        attribution = "OK" if correct else "ABSTAIN_FAIL"
    elif item.expected_behavior == "clarify":
        attribution = "OK" if correct else ("ROUTE_WRONG_OPTIONS" if trace.route == "clarified" else "ROUTE_MISSED_CLARIFY")
    elif correct:
        attribution = "OK_UNGROUNDED" if ev_ctx is False else "OK"
    elif trace.observability == "L0" or ev_ctx is None:
        attribution = "UNDETERMINED_L0"
    elif ev_ctx:
        if abstained:
            attribution = "GEN_OVER_ABSTAIN"
        elif item.expected_values and _numbers(answer):
            ctx_numbers = set(_numbers(" ".join(c.text for c in trace.context)))
            expected = {(_numbers(str(v.get("value") if isinstance(v, dict) else v)) or [""])[0] for v in item.expected_values}
            attribution = "GEN_NUMBER_EXTRACTION" if expected & ctx_numbers else "GEN_NUMBER_FABRICATED"
        else:
            attribution = "GEN_WRONG_OTHER"
    elif ev_rank:
        attribution = "CONTEXT_DROP"
    elif ev_cand:
        attribution = "RERANK_DROP"
    elif trace.observability == "L3":
        attribution = "RETRIEVAL_MISS"
    else:
        attribution = "RETRIEVAL_MISS"
    return ItemEvaluation(
        question_id=item.id,
        correct=correct,
        evidence_in_candidates=ev_cand,
        evidence_in_ranked=ev_rank,
        evidence_in_context=ev_ctx,
        answer=answer,
        reason=reason,
        attribution=attribution,
        latency_ms=trace.latency_ms,
    )


def _is_abstained(trace: QuestionTrace) -> bool:
    if trace.route == "abstained":
        return True
    return trace.answer is not None and trace.answer.abstained


def evaluate(items: list[GoldenItem], traces: list[QuestionTrace], ks: tuple[int, ...] = (1, 3, 5, 10)) -> dict[str, Any]:
    by_id = {trace.question_id: trace for trace in traces}
    missing = [item.id for item in items if item.id not in by_id]
    rows = [evaluate_item(item, by_id[item.id]) for item in items if item.id in by_id]
    correct = sum(row.correct is True for row in rows)
    evaluated = sum(row.correct is not None for row in rows)
    counts = Counter(row.attribution for row in rows)
    abstain_gold = [item for item in items if item.expected_behavior == "abstain" and item.id in by_id]
    retrieval_n = sum(bool(item.evidence) and item.id in by_id for item in items)
    abstain_hits = sum(_is_abstained(by_id[item.id]) for item in abstain_gold)
    predicted_abstentions = [trace for trace in traces if _is_abstained(trace)]
    metrics: dict[str, Any] = {
        "n": evaluated,
        "retrieval_n": retrieval_n,
        "accuracy": correct / evaluated if evaluated else None,
        "attribution_counts": dict(counts),
        "missing_question_ids": missing,
        "abstain_recall": abstain_hits / len(abstain_gold) if abstain_gold else None,
        "abstain_precision": abstain_hits / len(predicted_abstentions) if predicted_abstentions else None,
        "abstain_n": len(abstain_gold),
    }
    for k in ks:
        candidate_hits: list[bool] = []
        final_hits: list[bool] = []
        reciprocal: list[float] = []
        candidate_recalls: list[float] = []
        final_recalls: list[float] = []
        candidate_ndcgs: list[float] = []
        ndcgs: list[float] = []
        for item in items:
            if not item.evidence:
                continue
            trace = by_id.get(item.id)
            if not trace:
                continue
            candidates = trace.candidates[:k]
            order = (trace.ranked or trace.context or trace.candidates)[:k]
            candidate_relevant = [_chunk_has_evidence(chunk, item) for chunk in candidates]
            relevant = [_chunk_has_evidence(c, item) for c in order]
            candidate_hits.append(_list_has_evidence(candidates, item) is True)
            final_hits.append(_list_has_evidence(order, item) is True)
            candidate_evidence_found = sum(any(_chunk_matches(c, evidence) for c in candidates) for evidence in item.evidence)
            final_evidence_found = sum(any(_chunk_matches(c, evidence) for c in order) for evidence in item.evidence)
            candidate_recalls.append(candidate_evidence_found / len(item.evidence) if item.evidence else 0.0)
            final_recalls.append(final_evidence_found / len(item.evidence) if item.evidence else 0.0)
            reciprocal.append(1 / (relevant.index(True) + 1) if True in relevant else 0.0)
            candidate_dcg = sum(1 / math.log2(rank + 2) for rank, is_relevant in enumerate(candidate_relevant) if is_relevant)
            candidate_ideal = sum(1 / math.log2(rank + 2) for rank in range(sum(candidate_relevant)))
            candidate_ndcgs.append(candidate_dcg / candidate_ideal if candidate_ideal else 0.0)
            dcg = sum(1 / math.log2(rank + 2) for rank, is_relevant in enumerate(relevant) if is_relevant)
            ideal_count = sum(relevant)
            ideal_dcg = sum(1 / math.log2(rank + 2) for rank in range(ideal_count))
            ndcgs.append(dcg / ideal_dcg if ideal_dcg else 0.0)
        metrics[f"candidate_hit@{k}"] = sum(candidate_hits) / len(candidate_hits) if candidate_hits else None
        metrics[f"hit@{k}"] = sum(final_hits) / len(final_hits) if final_hits else None
        metrics[f"candidate_recall@{k}"] = sum(candidate_recalls) / len(candidate_recalls) if candidate_recalls else None
        metrics[f"recall@{k}"] = sum(final_recalls) / len(final_recalls) if final_recalls else None
        metrics[f"mrr@{k}"] = sum(reciprocal) / len(reciprocal) if reciprocal else None
        metrics[f"candidate_ndcg@{k}"] = sum(candidate_ndcgs) / len(candidate_ndcgs) if candidate_ndcgs else None
        metrics[f"ndcg@{k}"] = sum(ndcgs) / len(ndcgs) if ndcgs else None
        metrics[f"rerank_gain@{k}"] = (metrics[f"hit@{k}"] - metrics[f"candidate_hit@{k}"]
                                               if final_hits and candidate_hits else None)
        metrics[f"hit@{k}_ci95"] = list(wilson_ci(sum(final_hits), len(final_hits))) if final_hits else None
    metrics["accuracy_ci95"] = list(wilson_ci(correct, evaluated)) if evaluated else None
    return {"metrics": metrics, "items": [r.model_dump(mode="json") for r in rows]}


def _rate(rows: list[ItemEvaluation], condition: Any) -> float | None:
    return sum(bool(condition(r)) for r in rows) / len(rows) if rows else None
