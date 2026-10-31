from __future__ import annotations

import functools
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from ragnoz.schemas import (
    ArchitectureProfile,
    EvidenceRef,
    Finding,
    GoldenItem,
    ItemEvaluation,
    QuestionTrace,
    Recommendation,
)
from ragnoz.statistics import wilson_ci

RULES_DIR = Path(__file__).resolve().parent.parent / "data" / "rules"


@functools.cache
def _catalog() -> dict[str, Any]:
    return yaml.safe_load((RULES_DIR / "catalog.yaml").read_text(encoding="utf-8")) or {}


@functools.cache
def _rule(rule_id: str) -> dict[str, Any]:
    return yaml.safe_load((RULES_DIR / f"{rule_id}.yaml").read_text(encoding="utf-8")) or {}


CORE_RULES = _catalog()["core_rules"]
ALL_RULE_IDS = [*CORE_RULES, "DECL_MISMATCH"]


def rules_by_symptom() -> dict[str, list[str]]:
    """Reverse index: symptom id -> rule ids declaring it (used by ragnoz.diagnosis.triage)."""
    mapping: dict[str, list[str]] = defaultdict(list)
    for rule_id in ALL_RULE_IDS:
        for symptom in _rule(rule_id).get("symptoms", []):
            mapping[symptom].append(rule_id)
    return dict(mapping)


def load_architecture(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {}
    if raw.get("inspected_draft"):
        raise ValueError(
            f"{path} bir inspect taslağıdır (ölçülmüş girdi değil). Önce onaylayın: "
            "ragnoz architecture approve <taslak> --output architecture.yaml"
        )
    return raw


def _module(profile: dict[str, Any], name: str) -> Any:
    return (profile.get("modules") or {}).get(name)


def _contains_reranker(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value.get("rerank") or value.get("reranker") or value.get("cross_encoder"))
    if isinstance(value, str):
        return bool(value.strip()) and value.lower() not in {"none", "null", "false"}
    return bool(value)


def discover_architecture(
    traces: list[QuestionTrace], declaration: dict[str, Any] | None = None, system: str = "unknown"
) -> ArchitectureProfile:
    declaration = declaration or {}
    modules = declaration.get("modules", {}) or {}
    facts: list[dict[str, Any]] = []
    mismatches: list[str] = []
    unknowns: list[str] = []
    levels = [int(t.observability or "L0"[-1:]) if False else int((t.observability or "L0")[1:]) for t in traces]
    level = cast(Literal["L0", "L1", "L2", "L3"], f"L{max(levels, default=0)}")
    flow = declaration.get("flow", "unknown")
    routes = {t.route_label for t in traces if t.route_label}
    if flow == "unknown" and routes:
        flow = "conditional" if len(routes) > 1 else "linear"
        facts.append({"fact": "flow", "value": flow, "source": "trace", "confidence": "medium"})
    rounds = [t.retrieval_rounds for t in traces if t.retrieval_rounds is not None]
    if flow == "unknown" and rounds and max(rounds) > 1:
        flow = "loop"
    declared_rerank = _contains_reranker(modules.get("post_retrieval") or modules.get("reranker"))
    changed_order = sum(bool(t.candidates and t.ranked and [c.doc_id for c in t.candidates] != [c.doc_id for c in t.ranked]) for t in traces)
    if declared_rerank:
        facts.append({"fact": "reranker", "value": "present", "source": "declaration", "confidence": "high"})
        if traces and all(t.candidates and t.ranked and [c.doc_id for c in t.candidates] == [c.doc_id for c in t.ranked] for t in traces):
            mismatches.append("Reranker beyan edilmiş; ancak aday ve son listeler gözlenen tüm izlerde aynı.")
    elif changed_order:
        facts.append({"fact": "reranker", "value": "observed", "source": "trace", "confidence": "high"})
    elif level in {"L0", "L1"}:
        unknowns.append("Reranker'ın varlığı iz seviyesinden belirlenemiyor.")
    if not modules:
        unknowns.append("Mimari beyan dosyası yok; gözlenemeyen modüller bilinmiyor olarak bırakıldı.")
    for key, value in modules.items():
        facts.append({"fact": key, "value": value, "source": "declaration", "confidence": "high"})
    pre = _module(declaration, "pre_retrieval")
    post = _module(declaration, "post_retrieval")
    orchestration = _module(declaration, "orchestration")
    if flow in {"conditional", "branching", "loop"} or orchestration:
        paradigm: Literal["Naive", "Advanced", "Modular", "Undetermined"] = "Modular"
    elif pre or post:
        paradigm = "Advanced"
    elif modules or traces:
        paradigm = "Naive"
    else:
        paradigm = "Undetermined"
    return ArchitectureProfile(
        system=declaration.get("system", system), paradigm=paradigm,
        flow=cast(Literal["linear", "conditional", "branching", "loop", "unknown"], flow if flow in {"linear", "conditional", "branching", "loop"} else "unknown"),
        observability=level, modules=modules, facts=facts, mismatches=mismatches, unknowns=unknowns,
    )


def _make_finding(rule: str, title: str, module: str, ids: list[str], measured: str, threshold: str, level: str, explanation: str, confidence: str = "medium") -> Finding:
    return Finding(id=rule, title=title, module=module, severity="warning", measured=measured, threshold=threshold,
                   item_ids=ids, observability=cast(Literal["L0", "L1", "L2", "L3"], level),
                   confidence=cast(Literal["low", "medium", "high"], confidence), explanation=explanation)


def diagnose(
    items: list[GoldenItem], traces: list[QuestionTrace], evaluations: list[ItemEvaluation],
    architecture: dict[str, Any] | None = None, run_id: str = "local", ablations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    architecture = architecture or {}
    ablations = ablations or {}
    trace_by_id = {t.question_id: t for t in traces}
    eval_by_id = {e.question_id: e for e in evaluations}
    profile = discover_architecture(traces, architecture, system=run_id)
    findings: list[Finding] = []
    recommendations: list[Recommendation] = []
    rec_n = 0

    def add(rule_id: str, ids: list[str], measured_kwargs: dict[str, Any], impact: int | None = None,
            module_override: str | None = None, threshold_kwargs: dict[str, Any] | None = None,
            experiment_overrides: dict[str, Any] | None = None) -> None:
        nonlocal rec_n
        if not ids:
            return
        spec = _rule(rule_id)
        measured = spec["measured_template"].format(**measured_kwargs)
        threshold = spec["threshold_template"].format(**{**spec.get("params", {}), **(threshold_kwargs or {})})
        confidence = spec.get("confidence_default", "medium")
        module = module_override or spec["module"]
        why = spec["explanation"]
        findings.append(_make_finding(rule_id, spec["title"], module, ids, measured, threshold, level, why, confidence))
        rec_n += 1
        n = len(ids)
        interval = wilson_ci(min(n, len(ids)), max(1, len(traces)))
        experiment = {**spec["experiment"]}
        if experiment_overrides:
            overrides = dict(experiment_overrides)
            success_override = overrides.pop("success", None)
            experiment.update(overrides)
            if success_override:
                experiment = {**experiment, "success": {**experiment.get("success", {}), **success_override}}
        recommendation_confidence = "low" if confidence == "low" or n < 5 else ("high" if experiment.get("passed") else "medium")
        rec_id = f"rec-{rec_n:03d}"
        recommendations.append(Recommendation(
            id=rec_id, rule_id=rule_id, target_module=module,
            findings=[EvidenceRef(metric=measured, value=float(n), ci95=interval, n=len(traces), item_ids=ids)],
            hypothesis=why, change=spec["change"], alternatives=spec.get("alternatives", []),
            expected_impact={"metric": "accuracy", "upper_bound_items": impact if impact is not None else len(ids),
                             "basis": "Bu run'da ilgili ilk kırılma noktasına sahip soru sayısı; başarı garantisi değildir."},
            confidence=cast(Literal["low", "medium", "high"], recommendation_confidence),
            confidence_reasons=["Güven sıralı etikettir; deney öncesi en fazla Orta.", f"Gözlem {level}; etkilenen soru n={n}."] + (["Başarı ölçütünü geçen ablasyon/A-B deneyi kaydı var."] if recommendation_confidence == "high" else []),
            cost_risk=spec.get("risk") or ["Öneri hipotezdir; ölçülmemiş gecikme/maliyet etkisi bu izlerden çıkarılamaz."],
            experiment={**experiment, "id": rec_id, "reuse_cache_until": experiment.get("reuse_cache_until", "stage-before-change")},
            cannot_infer=["Modelin alan verisiyle fine-tune edilip edilmediği.", "Gerçek kullanıcı soru dağılımına genelleme."],
        ))

    level = profile.observability
    errors = {eid: eval_by_id[eid].attribution for eid in eval_by_id}
    by_code = lambda code: [eid for eid, value in errors.items() if value == code]
    absent = [eid for eid, t in trace_by_id.items() if t.answer and not t.answer.abstained and t.route != "abstained"]
    unanswered = [i.id for i in items if i.expected_behavior == "abstain"]
    not_refused = [qid for qid in unanswered if qid in trace_by_id and qid in absent]
    p = _rule("AP-05")["params"]
    if len(unanswered) >= p["min_unanswered"] and len(not_refused) >= p["min_not_refused"]:
        add("AP-05", not_refused, {"not_refused": len(not_refused), "unanswered": len(unanswered)})

    boundary = by_code("CHUNK_BOUNDARY")
    p = _rule("AP-02")["params"]
    if len(boundary) >= p["min_count"] and len(boundary) / max(1, len(items)) >= p["min_fraction"]:
        add("AP-02", boundary, {"count": len(boundary), "total": len(items)}, impact=len(boundary))

    modules = architecture.get("modules", {}) or {}
    indexing = modules.get("indexing", {}) or {}
    chunking = indexing.get("chunking", {}) or {}
    retrieval = modules.get("retrieval", {}) or {}
    retriever = retrieval.get("retriever", {}) or {}
    chunk_size = int(chunking.get("size_tokens", 0) or 0) if isinstance(chunking, dict) else 0
    top_k = int(architecture.get("top_k", 0) or retrieval.get("top_k", 0) or 0)
    context_window = int(architecture.get("context_window_tokens", 0) or 0)
    ap01_params = _rule("AP-01")["params"]
    budget = int(ap01_params["budget_ratio"] * context_window) if context_window else 0
    if chunk_size and top_k and budget and chunk_size * top_k > budget:
        affected = [t.question_id for t in traces if t.context]
        add("AP-01", affected, {"chunk_size": chunk_size, "top_k": top_k, "product": chunk_size * top_k, "budget": budget},
            threshold_kwargs={"context_window": context_window})

    cand_only = [eid for eid, ev in eval_by_id.items() if ev.evidence_in_candidates and not ev.evidence_in_context and ev.correct is False]
    reranker_declared = bool((architecture.get("modules") or {}).get("post_retrieval"))
    p = _rule("AP-03")["params"]
    if level in {"L2", "L3"} and cand_only and not reranker_declared and len(cand_only) >= p["min_count"]:
        add("AP-03", cand_only, {"count": len(cand_only)}, impact=len(cand_only))

    wrong_with_evidence = [eid for eid, ev in eval_by_id.items() if ev.correct is False and ev.evidence_in_context]
    p = _rule("AP-04")["params"]
    if top_k >= p["min_top_k"] and len(wrong_with_evidence) >= p["min_count"]:
        add("AP-04", wrong_with_evidence, {"top_k": top_k, "count": len(wrong_with_evidence)}, impact=len(wrong_with_evidence))

    numeric_errors = by_code("GEN_NUMBER_EXTRACTION")
    numeric_total = [i.id for i in items if i.type == "numeric"]
    p = _rule("AP-12")["params"]
    if len(numeric_errors) >= p["min_count"] and len(numeric_errors) / max(1, len(numeric_total)) >= p["min_fraction"]:
        add("AP-12", numeric_errors, {"count": len(numeric_errors), "total": len(numeric_total)}, impact=len(numeric_errors))

    if profile.mismatches:
        ids = [t.question_id for t in traces if t.candidates and t.ranked and [c.doc_id for c in t.candidates] == [c.doc_id for c in t.ranked]]
        spec = _rule("DECL_MISMATCH")
        findings.append(_make_finding("DECL_MISMATCH", spec["title"], spec["module"], ids, spec["measured_template"],
                                      spec["threshold_template"], level, spec["explanation"], spec.get("confidence_default", "medium")))

    if len(traces) and all(t.candidates for t in traces) and all(t.ranked for t in traces):
        gain_ids = [t.question_id for t in traces if t.candidates and t.ranked and [c.doc_id for c in t.candidates] == [c.doc_id for c in t.ranked]]
        if reranker_declared and len(gain_ids) == len(traces):
            add("AP-09", gain_ids, {"count": len(gain_ids), "total": len(traces)})

    lang_groups: dict[str, list[str]] = defaultdict(list)
    for item in items:
        if item.id in eval_by_id and item.type != "unanswerable":
            lang_groups[item.lang].append(item.id)
    if len(lang_groups) >= 2:
        rates = {}
        for lang, ids in lang_groups.items():
            valid = [eval_by_id[i] for i in ids if eval_by_id[i].evidence_in_candidates is not None]
            rates[lang] = sum(e.evidence_in_candidates is True for e in valid) / len(valid) if valid else 0
        if len(rates) >= 2:
            low, high = min(rates, key=lambda key: rates[key]), max(rates, key=lambda key: rates[key])
            p = _rule("AP-07")["params"]
            if len(lang_groups[low]) >= p["min_group_size"] and len(lang_groups[high]) >= p["min_group_size"] and rates[high] - rates[low] >= p["min_diff"]:
                affected = [i for i in lang_groups[low] if eval_by_id[i].evidence_in_candidates is False]
                add("AP-07", affected, {"low": low, "high": high, "rate_low": f"{rates[low]:.2f}", "rate_high": f"{rates[high]:.2f}"},
                    impact=len(affected), experiment_overrides={"success": {"group": low}})

    exact_ids = [i.id for i in items if i.type == "exact_id" or "exact_id" in i.tags]
    retrieval_ops = retriever.get("operators", []) if isinstance(retriever, dict) else []
    operator = retriever.get("operator", "") if isinstance(retriever, dict) else ""
    dense_only = operator == "dense" or ("dense" in retrieval_ops and "bm25" not in retrieval_ops)
    exact_misses = [qid for qid in exact_ids if qid in eval_by_id and eval_by_id[qid].evidence_in_candidates is False]
    p = _rule("AP-08")["params"]
    if dense_only and len(exact_ids) >= p["min_exact_ids"] and len(exact_misses) >= p["min_misses"]:
        add("AP-08", exact_misses, {"count": len(exact_misses), "total": len(exact_ids)}, impact=len(exact_misses))

    removal = ablations.get("remove") if isinstance(ablations, dict) else None
    p = _rule("AP-13")["params"]
    if (isinstance(removal, dict) and removal.get("passed")
            and removal.get("accuracy_delta_ci95", [0, 0])[0] <= 0 <= removal.get("accuracy_delta_ci95", [0, 0])[1]
            and float(removal.get("latency_cost_delta", 0)) >= p["min_latency_cost_delta"]):
        module_name = str(removal.get("module", "module"))
        add("AP-13", list(removal.get("item_ids", [])) or [t.question_id for t in traces],
            {"delta_pct": f"{float(removal.get('latency_cost_delta', 0)):.0%}"},
            module_override=module_name, experiment_overrides={"stage": module_name})

    oracle = ablations.get("oracle_context") if isinstance(ablations, dict) else None
    no_context = ablations.get("no_context") if isinstance(ablations, dict) else None
    p = _rule("AP-18")["params"]
    if isinstance(oracle, dict) and isinstance(no_context, dict) and len(traces) >= p["min_traces"]:
        oracle_gain = float(oracle.get("accuracy_delta", 0))
        no_context_delta = float(no_context.get("accuracy_delta", 0))
        affected = [qid for qid, ev in eval_by_id.items() if ev.correct is False and ev.evidence_in_context]
        if abs(oracle_gain) < p["max_delta"] and abs(no_context_delta) < p["max_delta"] and affected:
            add("AP-18", affected, {"oracle_fmt": f"{oracle_gain:.3f}", "no_context_fmt": f"{no_context_delta:.3f}"}, impact=len(affected))

    catalog = _catalog()
    return {
        "profile": profile.model_dump(mode="json"),
        "findings": [f.model_dump(mode="json") for f in findings],
        "recommendations": [r.model_dump(mode="json") for r in recommendations],
        "rule_catalog": {"version": catalog["version"], "core_rules": CORE_RULES, "deferred_rules": catalog["deferred_rules"]},
        "cannot_infer": catalog["cannot_infer"],
        "run_id": run_id,
    }
