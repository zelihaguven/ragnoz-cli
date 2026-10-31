from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from ragnoz.cache import StageCache
from ragnoz.cli._shared import (
    _evaluate_adapter_instance,
    _json_write,
    _load_adapter,
    _read_traces,
    _scrub,
    app,
    console,
    experiment_cli,
)
from ragnoz.compare import compare_evaluations
from ragnoz.evaluation import evaluate
from ragnoz.golden import golden_hash, load_golden
from ragnoz.importers import write_jsonl


@app.command("ablate")
def ablate_command(
    ablation: str = typer.Option(..., "--type", help="remove, swap, oracle-context, no-context veya config-diff"),
    module: str = typer.Option(..., "--module"),
    traces: Path | None = typer.Option(None, "--traces", exists=True, readable=True),
    adapter: str | None = typer.Option(None, "--adapter"),
    golden: Path | None = typer.Option(None, "--golden", exists=True, readable=True),
    cache_dir: Path = typer.Option(Path(".ragnoz/cache"), "--cache-dir"),
    output: Path = typer.Option(Path(".ragnoz/ablation.json"), "--output"),
) -> None:
    allowed = {"remove", "swap", "oracle-context", "no-context", "config-diff"}
    if ablation not in allowed:
        raise typer.BadParameter("Tür remove, swap, oracle-context, no-context veya config-diff olmalı")
    result: dict[str, Any] = {"type": ablation, "module": module, "status": "inconclusive", "executed": False,
        "run": None, "reason": "Adapter ile ablasyon çalıştırılmadı; yalnızca taslak kaydedildi.",
        "cannot_infer": ["Model/arayıcı nedensel etkisi", "Başarı veya gerileme", "Canlı gecikme/maliyet"]}
    if traces:
        result["source_trace_file"] = str(traces)
        result["trace_count"] = len(_read_traces(traces))
    if adapter:
        if not golden:
            raise typer.BadParameter("Adapter ablasyonu için --golden zorunludur")
        base_adapter = _load_adapter(adapter)
        intervention = getattr(base_adapter, "with_ablation", None)
        if callable(intervention):
            variant_adapter = intervention(ablation, module)
            items = load_golden(golden)
            cache = StageCache(cache_dir)
            baseline_traces, baseline_eval, _ = _evaluate_adapter_instance(base_adapter, items, cache, False, f"{adapter}:baseline")
            variant_traces, variant_eval, _ = _evaluate_adapter_instance(variant_adapter, items, cache, False, f"{adapter}:{ablation}")
            comparison = compare_evaluations(baseline_eval, variant_eval)
            run_dir = output.parent / (output.stem + "-runs")
            write_jsonl(baseline_traces, run_dir / "baseline.jsonl")
            write_jsonl(variant_traces, run_dir / "variant.jsonl")
            b = comparison["mcnemar"]["b_before_correct_after_wrong"]
            c = comparison["mcnemar"]["c_before_wrong_after_correct"]
            passed = comparison["mcnemar"]["p_value_exact"] < 0.05 and c > b
            result.update({"executed": True, "status": "verified" if passed else "inconclusive",
                "reason": "Eşleştirilmiş offline adapter müdahalesi çalıştırıldı.", "comparison": comparison,
                "confidence_after_experiment": "high" if passed else "medium", "cache": cache.stats(),
                "baseline_traces": str(run_dir / "baseline.jsonl"), "variant_traces": str(run_dir / "variant.jsonl")})
        else:
            result["reason"] = "Adapter with_ablation(type, module) sağlamıyor; müdahale çalıştırılmadı."
    _json_write(output, result)
    console.print(f"Ablasyon: {result['status']} · {'çalıştırıldı' if result['executed'] else 'taslak'} · {output}")


@experiment_cli.command("run")
def experiment_run(
    recommendation_id: str = typer.Argument(...),
    before: Path | None = typer.Option(None, "--before", exists=True, readable=True),
    after: Path | None = typer.Option(None, "--after", exists=True, readable=True),
    golden: Path | None = typer.Option(None, "--golden", exists=True, readable=True),
    adapter: str | None = typer.Option(None, "--adapter"),
    cache_dir: Path = typer.Option(Path(".ragnoz/cache"), "--cache-dir"),
    output: Path = typer.Option(Path(".ragnoz/experiment.json"), "--output"),
    max_regressions: int = typer.Option(2, "--max-regressions", min=0),
) -> None:
    if not golden:
        raise typer.BadParameter("--golden zorunludur")
    items = load_golden(golden)
    demo_only = False
    if adapter:
        base_adapter = _load_adapter(adapter)
        experiment = getattr(base_adapter, "with_experiment", None)
        if not callable(experiment):
            result = {"recommendation_id": recommendation_id, "status": "inconclusive", "executed": False,
                      "reason": "Adapter with_experiment(rec-id) sağlamıyor; öneri doğrulanmadı.",
                      "config_diff": _scrub(getattr(base_adapter, "config", {}))}
            _json_write(output, result)
            console.print(f"Deney {recommendation_id}: inconclusive · adapter hook yok · {output}")
            return
        variant_adapter = experiment(recommendation_id)
        cache = StageCache(cache_dir)
        baseline_traces, baseline_eval, _ = _evaluate_adapter_instance(base_adapter, items, cache, False, f"{adapter}:baseline")
        variant_traces, variant_eval, _ = _evaluate_adapter_instance(variant_adapter, items, cache, False, f"{adapter}:{recommendation_id}")
        description = base_adapter.describe() if callable(getattr(base_adapter, "describe", None)) else {}
        demo_only = any(trace.synthetic_fixture for trace in baseline_traces + variant_traces)
        demo_only = demo_only or "wiki-mini" in str(description.get("system", "")).casefold()
        run_dir = output.parent / (output.stem + "-runs")
        write_jsonl(baseline_traces, run_dir / "baseline.jsonl")
        write_jsonl(variant_traces, run_dir / "variant.jsonl")
        comparison = compare_evaluations(baseline_eval, variant_eval)
        baseline_source, variant_source = str(run_dir / "baseline.jsonl"), str(run_dir / "variant.jsonl")
        cache_stats = cache.stats()
    elif before and after:
        baseline_traces = _read_traces(before)
        variant_traces = _read_traces(after)
        demo_only = any(trace.synthetic_fixture for trace in baseline_traces + variant_traces)
        baseline = evaluate(items, baseline_traces)
        variant = evaluate(items, variant_traces)
        comparison = compare_evaluations(baseline, variant)
        baseline_source, variant_source = str(before), str(after)
        cache_stats = None
    else:
        raise typer.BadParameter("Sağlanan adapter ile veya --before/--after iz dosyalarıyla çalıştırın")
    passed = (not demo_only and comparison["mcnemar"]["p_value_exact"] < 0.05 and
              comparison["mcnemar"]["c_before_wrong_after_correct"] > comparison["mcnemar"]["b_before_correct_after_wrong"] and
              comparison["mcnemar"]["b_before_correct_after_wrong"] <= max_regressions)
    status = ("inconclusive" if demo_only else "verified" if passed else
              "refuted" if comparison["accuracy_delta"] is not None and comparison["accuracy_delta"] < 0 else "inconclusive")
    result = {"recommendation_id": recommendation_id, "status": status, "executed": True, "comparison": comparison,
              "success_criteria": {"test": "exact McNemar", "alpha": 0.05, "max_regressions": max_regressions},
              "confidence_after_experiment": "medium" if demo_only else "high" if passed else "low" if status == "refuted" else "medium",
              "synthetic_or_demo_only": demo_only,
              "scope_note": "Demo/fikstür sonucu gerçek RAG sisteminde öneriyi doğrulamaz." if demo_only else "",
              "baseline": baseline_source, "variant": variant_source, "cache": cache_stats,
              "golden_sha256": golden_hash(items)}
    _json_write(output, result)
    console.print(f"Deney {recommendation_id}: {status} · accuracy Δ={comparison['accuracy_delta']} · exact p={comparison['mcnemar']['p_value_exact']:.4f}")
    console.print(f"Sonuç: {output}")
