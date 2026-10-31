from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from ragnoz.cache import StageCache
from ragnoz.cli._shared import (
    _evaluate_adapter_instance,
    _json_write,
    _load_adapter,
    _print_metrics,
    _read_traces,
    _write_summary,
    app,
    console,
)
from ragnoz.compare import compare_evaluations
from ragnoz.evaluation import evaluate
from ragnoz.golden import golden_hash, load_golden
from ragnoz.importers import import_jsonl, write_jsonl
from ragnoz.schemas import QuestionTrace


def _run_eval(golden_path: str | Path, trace_path: str | Path) -> tuple[list[Any], list[QuestionTrace], dict[str, Any]]:
    items = load_golden(golden_path)
    traces = _read_traces(trace_path)
    result = evaluate(items, traces)
    return items, traces, result


def _run_adapter(adapter_spec: str, golden: Path, cache_dir: Path, no_cache: bool) -> tuple[Any, list[QuestionTrace], dict[str, Any], dict[str, Any]]:
    adapter = _load_adapter(adapter_spec)
    items = load_golden(golden)
    traces, evaluated, diagnosis = _evaluate_adapter_instance(
        adapter, items, StageCache(cache_dir), no_cache, run_id=adapter_spec,
    )
    return items, traces, evaluated, diagnosis


@app.command("import")
def import_traces(path: Path = typer.Argument(..., exists=True, readable=True), output: Path = typer.Option(Path(".ragnoz/imported.jsonl"), "--output"), mapping: Path | None = typer.Option(None, "--mapping", exists=True, readable=True)) -> None:
    traces = import_jsonl(path, mapping)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for trace in traces:
            stream.write(json.dumps(trace.model_dump(mode="json", exclude_none=True), ensure_ascii=False, sort_keys=True) + "\n")
    console.print(f"{len(traces)} iz içe aktarıldı: {output}")


@app.command("eval")
def evaluate_command(golden: Path = typer.Option(..., "--golden", exists=True, readable=True), traces: Path = typer.Option(..., "--traces", exists=True, readable=True), output: Path = typer.Option(Path(".ragnoz/runs"), "--output")) -> None:
    items, trace_rows, result = _run_eval(golden, traces)
    _print_metrics(result["metrics"])
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    run_dir = output / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _json_write(run_dir / "metrics.json", result["metrics"])
    _json_write(run_dir / "manifest.json", {"run_id": run_id, "created_utc": datetime.now(UTC).isoformat(),
        "golden_sha256": golden_hash(items), "golden_count": len(items), "trace_count": len(trace_rows),
        "tool_version": "0.1.0", "seed": 0, "source": str(traces)})
    with (run_dir / "results.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for row in result["items"]:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    _write_summary(run_dir / "summary.md", result)
    console.print(f"Run {run_id}: {run_dir}")


@app.command("run")
def run_command(
    golden: Path = typer.Option(..., "--golden", exists=True, readable=True),
    adapter: str = typer.Option(..., "--adapter", help="module:function veya /path/to/adapter.py:function"),
    output: Path = typer.Option(Path(".ragnoz/runs"), "--output"),
    cache_dir: Path = typer.Option(Path(".ragnoz/cache"), "--cache-dir"),
    no_cache: bool = typer.Option(False, "--no-cache"),
) -> None:
    """Altı aşamalı adapter pipeline'ını çalıştır, ölç ve yerel artefaktları yaz."""
    try:
        items, traces, result, diagnosis = _run_adapter(adapter, golden, cache_dir, no_cache)
    except Exception as exc:
        console.print(f"[red]Adapter çalıştırılamadı:[/red] {type(exc).__name__}; ham hata metni gizlilik için atlandı.")
        raise typer.Exit(1) from exc
    _print_metrics(result["metrics"], "RAGnoz run")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    run_dir = output / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(traces, run_dir / "traces.jsonl")
    with (run_dir / "results.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for row in result["items"]:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    _json_write(run_dir / "metrics.json", result["metrics"])
    _json_write(run_dir / "diagnosis.json", diagnosis)
    _write_summary(run_dir / "summary.md", result, diagnosis)
    _json_write(run_dir / "manifest.json", {
        "run_id": run_id, "created_utc": datetime.now(UTC).isoformat(), "adapter": adapter,
        "golden_sha256": golden_hash(items), "golden_count": len(items), "trace_count": len(traces),
        "tool_version": "0.1.0", "cache": diagnosis["cache"], "cache_disabled": no_cache,
    })
    console.print(f"Cache: {diagnosis['cache']['hits']} isabet · {diagnosis['cache']['misses']} kaçırma")
    console.print(f"Run {run_id}: {run_dir}")


@app.command("compare")
def compare_command(before: Path = typer.Option(..., "--before", exists=True, readable=True), after: Path = typer.Option(..., "--after", exists=True, readable=True), golden: Path = typer.Option(..., "--golden", exists=True, readable=True), output: Path = typer.Option(Path(".ragnoz/compare.json"), "--output")) -> None:
    items = load_golden(golden)
    left = evaluate(items, _read_traces(before))
    right = evaluate(items, _read_traces(after))
    result = compare_evaluations(left, right)
    _json_write(output, result)
    questions = Table(title="Soru bazında önce/sonra")
    questions.add_column("Question ID")
    questions.add_column("Geçiş")
    questions.add_column("Önce doğru")
    questions.add_column("Sonra doğru")
    questions.add_column("Atıf: önce → sonra")
    for row in result["question_transitions"]:
        questions.add_row(row["question_id"], row["transition"], str(row["before_correct"]),
                          str(row["after_correct"]), f"{row['before_attribution']} → {row['after_attribution']}")
    console.print(questions)
    table = Table(title="Eşleştirilmiş karşılaştırma")
    table.add_column("Metric"); table.add_column("Before", justify="right"); table.add_column("After", justify="right"); table.add_column("Δ", justify="right")
    def fmt(v: Any) -> str: return "—" if v is None else f"{v:.3f}"
    table.add_row("Accuracy", fmt(result["before_accuracy"]), fmt(result["after_accuracy"]), fmt(result["accuracy_delta"]))
    table.add_row("n", str(result["n"]), str(result["n"]), "—")
    table.add_row("McNemar exact p", "—", "—", fmt(result["mcnemar"]["p_value_exact"]))
    console.print(table)
    console.print(f"Düzelip bozulan soru: {result['mcnemar']['c_before_wrong_after_correct']} / {result['mcnemar']['b_before_correct_after_wrong']}")
    console.print(f"Soru geçişleri: {output}")
