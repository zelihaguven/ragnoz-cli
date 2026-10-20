from __future__ import annotations

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

CORE_RULES = ["AP-01", "AP-02", "AP-03", "AP-04", "AP-05", "AP-07", "AP-08", "AP-09", "AP-12", "AP-13", "AP-18"]


def load_architecture(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


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

    def add(rule: str, title: str, module: str, ids: list[str], measured: str, threshold: str, level: str,
            why: str, change: str, experiment: dict[str, Any], impact: int | None = None,
            confidence: str = "medium", alternatives: list[str] | None = None, risk: list[str] | None = None) -> None:
        nonlocal rec_n
        if not ids:
            return
        findings.append(_make_finding(rule, title, module, ids, measured, threshold, level, why, confidence))
        rec_n += 1
        n = len(ids)
        interval = wilson_ci(min(n, len(ids)), max(1, len(traces)))
        recommendation_confidence = "low" if confidence == "low" or n < 5 else ("high" if experiment.get("passed") else "medium")
        rec_id = f"rec-{rec_n:03d}"
        recommendations.append(Recommendation(
            id=rec_id, rule_id=rule, target_module=module,
            findings=[EvidenceRef(metric=measured, value=float(n), ci95=interval, n=len(traces), item_ids=ids)],
            hypothesis=why, change=change, alternatives=alternatives or [],
            expected_impact={"metric": "accuracy", "upper_bound_items": impact if impact is not None else len(ids),
                             "basis": "Bu run'da ilgili ilk kırılma noktasına sahip soru sayısı; başarı garantisi değildir."},
            confidence=cast(Literal["low", "medium", "high"], recommendation_confidence),
            confidence_reasons=["Güven sıralı etikettir; deney öncesi en fazla Orta.", f"Gözlem {level}; etkilenen soru n={n}."] + (["Başarı ölçütünü geçen ablasyon/A-B deneyi kaydı var."] if recommendation_confidence == "high" else []),
            cost_risk=risk or ["Öneri hipotezdir; ölçülmemiş gecikme/maliyet etkisi bu izlerden çıkarılamaz."],
            experiment={**experiment, "id": rec_id, "reuse_cache_until": experiment.get("reuse_cache_until", "stage-before-change")},
            cannot_infer=["Modelin alan verisiyle fine-tune edilip edilmediği.", "Gerçek kullanıcı soru dağılımına genelleme."],
        ))

    level = profile.observability
    errors = {eid: eval_by_id[eid].attribution for eid in eval_by_id}
    by_code = lambda code: [eid for eid, value in errors.items() if value == code]
    absent = [eid for eid, t in trace_by_id.items() if t.answer and not t.answer.abstained and t.route != "abstained"]
    unanswered = [i.id for i in items if i.expected_behavior == "abstain"]
    not_refused = [qid for qid in unanswered if qid in trace_by_id and qid in absent]
    if len(unanswered) >= 5 and len(not_refused) >= 1:
        add("AP-05", "Reddetme mekanizması yok / zayıf", "generation", not_refused,
            f"cevapsız soru {len(not_refused)}/{len(unanswered)} reddedilmedi", "≥5 cevapsız soru ve reddetme duyarlılığı <0.5", level,
            "Cevapsız gold sorulara sistem yanıt verdi.", "Reddetme kuralı ve yapılandırılmış bulunamadı yanıtı ekleyin.",
            {"type": "prompt_ab", "stage": "generation", "success": {"metric": "abstain_recall", "minimum": 0.8}})

    boundary = by_code("CHUNK_BOUNDARY")
    if len(boundary) >= 3 and len(boundary) / max(1, len(items)) >= 0.10:
        add("AP-02", "Parça sınırı kanıtı bölüyor", "indexing.chunking", boundary,
            f"CHUNK_BOUNDARY={len(boundary)}/{len(items)}", "≥10% ve ≥3 soru", level,
            "Kanıt izlerde tek bir parçada tam olarak eşleşmiyor.", "Örtüşmeyi artırın veya yapı farkında parçalayıcıyı deneyin.",
            {"type": "swap", "stage": "chunker", "success": {"metric": "evidence_recall", "minimum_gain": 0.05}}, impact=len(boundary))

    modules = architecture.get("modules", {}) or {}
    indexing = modules.get("indexing", {}) or {}
    chunking = indexing.get("chunking", {}) or {}
    retrieval = modules.get("retrieval", {}) or {}
    retriever = retrieval.get("retriever", {}) or {}
    chunk_size = int(chunking.get("size_tokens", 0) or 0) if isinstance(chunking, dict) else 0
    top_k = int(architecture.get("top_k", 0) or retrieval.get("top_k", 0) or 0)
    context_window = int(architecture.get("context_window_tokens", 0) or 0)
    budget = int(0.9 * context_window) if context_window else 0
    if chunk_size and top_k and budget and chunk_size * top_k > budget:
        affected = [t.question_id for t in traces if t.context]
        add("AP-01", "Parça × top_k bağlam bütçesini aşıyor", "context", affected,
            f"{chunk_size}×{top_k}={chunk_size * top_k} token; pencere bütçesi={budget}",
            f"parça×top_k ≤0.9×{context_window}", level,
            "Beyan edilen üst sınır bağlam penceresinin %90'ını aşıyor; fiili kesilme izi ayrıca doğrulanmalıdır.",
            "Parça boyutunu veya top_k'yı düşürüp truncation oranını ölçün.",
            {"type": "sweep", "parameter": "chunk_size_tokens,top_k", "values": [[512, 5], [512, 8], [768, 5]],
             "success": {"metric": "truncated_rate", "maximum": 0.01}}, confidence="low")

    cand_only = [eid for eid, ev in eval_by_id.items() if ev.evidence_in_candidates and not ev.evidence_in_context and ev.correct is False]
    reranker_declared = bool((architecture.get("modules") or {}).get("post_retrieval"))
    if level in {"L2", "L3"} and cand_only and not reranker_declared and len(cand_only) >= 5:
        add("AP-03", "Yüksek aday recall'una rağmen yeniden sıralayıcı yok", "post_retrieval", cand_only,
            f"adaylarda kanıt var, son bağlamda yok: {len(cand_only)} soru", "L2+, ≥5 soru", level,
            "Aday listesinde bulunan doğru kanıt bazı yanlış cevaplarda son bağlama ulaşmadı.",
            "Cross-encoder yeniden sıralayıcı ekleyin.", {"type": "swap", "stage": "reranker", "success": {"test": "mcnemar_exact", "alpha": 0.05}},
            impact=len(cand_only), alternatives=["RRF ağırlıklarını ayarlayın", "top_k'yı ölçerek artırın"])

    wrong_with_evidence = [eid for eid, ev in eval_by_id.items() if ev.correct is False and ev.evidence_in_context]
    if top_k >= 10 and len(wrong_with_evidence) >= 5:
        add("AP-04", "top_k yüksek: dikkat dağılması olasılığı", "post_retrieval.context", wrong_with_evidence,
            f"top_k={top_k}; bağlam kanıtlı yanlış={len(wrong_with_evidence)}", "top_k≥10 ve ≥5 kanıtlı yanlış", level,
            "Yüksek top_k yanında kanıt bağlamda olmasına rağmen cevap yanlıştı; bu korelasyondur.",
            "top_k=3/5/10 taraması yapın; sonucu ayrı doğrulama sorularında teyit edin.",
            {"type": "sweep", "parameter": "top_k", "values": [3, 5, 10], "success": {"metric": "accuracy", "paired": True}},
            impact=len(wrong_with_evidence), confidence="low", risk=["Tarama çoklu karşılaştırma riski taşır; seçim ayrı sette doğrulanmalıdır."])

    numeric_errors = by_code("GEN_NUMBER_EXTRACTION")
    numeric_total = [i.id for i in items if i.type == "numeric"]
    if len(numeric_errors) >= 3 and len(numeric_errors) / max(1, len(numeric_total)) >= 0.20:
        add("AP-12", "Sayı çıkarma zayıf", "generation", numeric_errors,
            f"GEN_NUMBER_EXTRACTION={len(numeric_errors)}/{len(numeric_total)} sayısal soru", "≥20% ve ≥3 soru", level,
            "Kanıt bağlamdayken üretici beklenen değeri seçemedi.", "Sayıyı kanıt alıntısıyla birlikte çıkaran istem ve yapılandırılmış çıktı deneyin.",
            {"type": "prompt_ab", "stage": "generation", "success": {"metric": "numeric_accuracy", "context_fixed": True}}, impact=len(numeric_errors))

    if profile.mismatches:
        ids = [t.question_id for t in traces if t.candidates and t.ranked and [c.doc_id for c in t.candidates] == [c.doc_id for c in t.ranked]]
        findings.append(_make_finding("DECL_MISMATCH", "Beyan–davranış çelişkisi", "post_retrieval", ids,
                                      "Aday ve son liste sıraları aynı", "Beyan reranker içeriyor", level,
                                      "Beyan ile izler uyuşmuyor; bileşen etkisiz olabilir veya çıktısı kullanılmıyor.", "medium"))

    if len(traces) and all(t.candidates for t in traces) and all(t.ranked for t in traces):
        gain_ids = [t.question_id for t in traces if t.candidates and t.ranked and [c.doc_id for c in t.candidates] == [c.doc_id for c in t.ranked]]
        if reranker_declared and len(gain_ids) == len(traces):
            add("AP-09", "Reranker etkisiz olabilir", "post_retrieval.rerank", gain_ids,
                f"aday ve son sırası aynı: {len(gain_ids)}/{len(traces)}", "Rerank kazancı ≤0 veya beyan–iz çelişkisi", level,
                "Gözlenen aday sırası rerank sonrasında değişmedi.", "Reranker'ı çıkarıp/değiştirip eşleştirilmiş deney yapın.",
                {"type": "remove", "stage": "reranker", "success": {"test": "mcnemar_exact", "alpha": 0.05}}, confidence="low")

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
            if len(lang_groups[low]) >= 10 and len(lang_groups[high]) >= 10 and rates[high] - rates[low] >= 0.20:
                affected = [i for i in lang_groups[low] if eval_by_id[i].evidence_in_candidates is False]
                add("AP-07", "Soru ve belge dili uyumsuzluğu olabilir", "retrieval.embedding", affected,
                    f"aday hit {low}={rates[low]:.2f}, {high}={rates[high]:.2f}", "dil farkı ≥0.20; grup başına ≥10", level,
                    "Düşük hit oranı belirli soru dilinde yoğunlaşıyor.", "Çok dilli gömme modeli veya BM25 hibrit kolunu deneyin.",
                    {"type": "swap", "stage": "retriever", "success": {"metric": "hit@5", "group": low}}, impact=len(affected))

    exact_ids = [i.id for i in items if i.type == "exact_id" or "exact_id" in i.tags]
    retrieval_ops = retriever.get("operators", []) if isinstance(retriever, dict) else []
    operator = retriever.get("operator", "") if isinstance(retriever, dict) else ""
    dense_only = operator == "dense" or ("dense" in retrieval_ops and "bm25" not in retrieval_ops)
    exact_misses = [qid for qid in exact_ids if qid in eval_by_id and eval_by_id[qid].evidence_in_candidates is False]
    if dense_only and len(exact_ids) >= 3 and len(exact_misses) >= 3:
        add("AP-08", "Tam kimlikli sorgularda dense-only kaçırma", "retrieval", exact_misses,
            f"exact-ID miss={len(exact_misses)}/{len(exact_ids)}", "dense-only ve ≥3 kaçırma", level,
            "Tam kimlik / sembol sorgularında dense-only adaylar beklenen kanıtı bulamıyor.",
            "BM25+sparse retrieval kolunu ekleyip eşleştirilmiş top-k karşılaştırın.",
            {"type": "swap", "stage": "retriever", "success": {"metric": "exact_id_hit@k", "paired": True}}, impact=len(exact_misses))

    removal = ablations.get("remove") if isinstance(ablations, dict) else None
    if isinstance(removal, dict) and removal.get("passed") and removal.get("accuracy_delta_ci95", [0, 0])[0] <= 0 <= removal.get("accuracy_delta_ci95", [0, 0])[1] and float(removal.get("latency_cost_delta", 0)) >= 0.20:
        add("AP-13", "Ölçülen kazanç olmadan gereksiz karmaşıklık", str(removal.get("module", "module")),
            list(removal.get("item_ids", [])) or [t.question_id for t in traces],
            f"doğruluk farkı belirsiz; maliyet/gecikme +{float(removal.get('latency_cost_delta', 0)):.0%}",
            "McNemar/CI anlamlı kazanç göstermiyor ve maliyet ≥20%", level,
            "Modülü çıkarmak doğrulukta anlamlı kayıp göstermedi ve ölçülen maliyet en az %20 arttı.",
            "Modülü kaldırma/ucuzlatma varyantını bağımsız set üzerinde doğrulayın.",
            {"type": "remove", "stage": removal.get("module"), "success": {"test": "mcnemar_exact", "max_regressions": 2}},
            confidence="medium", risk=["Maliyet ölçümü çalışma ortamına ve trafik profiline bağlıdır."])

    oracle = ablations.get("oracle_context") if isinstance(ablations, dict) else None
    no_context = ablations.get("no_context") if isinstance(ablations, dict) else None
    if isinstance(oracle, dict) and isinstance(no_context, dict) and len(traces) >= 5:
        oracle_gain = float(oracle.get("accuracy_delta", 0))
        no_context_delta = float(no_context.get("accuracy_delta", 0))
        affected = [qid for qid, ev in eval_by_id.items() if ev.correct is False and ev.evidence_in_context]
        if abs(oracle_gain) < 0.02 and abs(no_context_delta) < 0.02 and affected:
            add("AP-18", "Üretici bağlamdan yararlanmıyor olabilir", "generation", affected,
                f"kâhin bağlam Δ={oracle_gain:.3f}; bağlamsız Δ={no_context_delta:.3f}",
                "oracle-context iyileştirmiyor ve no-context farkı <0.02", level,
                "Ablasyonlarda bağlam kalitesi/doğrudan kaldırılması çıktıyı değiştirmedi.",
                "Üreticiye yalnız verilen bağlamdan yanıt verme ve kaynak alıntısı kuralları ekleyin.",
                {"type": "oracle_context", "success": {"metric": "accuracy", "minimum_gain": 0.02}},
                impact=len(affected), confidence="medium")
    return {
        "profile": profile.model_dump(mode="json"),
        "findings": [f.model_dump(mode="json") for f in findings],
        "recommendations": [r.model_dump(mode="json") for r in recommendations],
        "rule_catalog": {"version": "0.1.0", "core_rules": CORE_RULES,
                         "deferred_rules": ["AP-06", "AP-10", "AP-11", "AP-14", "AP-15", "AP-16", "AP-17", "AP-19"]},
        "cannot_infer": ["Modelin fine-tune durumu", "Üretim dağılımına genelleme", "Gözlem seviyesi dışında kalan iç bileşenler", "Müdahale olmadan nedensellik"],
        "run_id": run_id,
    }
