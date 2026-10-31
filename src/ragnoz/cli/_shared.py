from __future__ import annotations

import importlib
import importlib.util
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from ragnoz.cache import StageCache
from ragnoz.diagnosis import diagnose as run_diagnosis
from ragnoz.evaluation import evaluate
from ragnoz.importers import import_jsonl
from ragnoz.runner import PipelineRunner
from ragnoz.schemas import ItemEvaluation, QuestionTrace

app = typer.Typer(no_args_is_help=True, help="Yerel-öncelikli RAG değerlendirme ve mimari teşhis aracı")
demo_cli = typer.Typer(no_args_is_help=True, help="Wikipedia mini-demo komutları")
golden_cli = typer.Typer(no_args_is_help=True, help="Altın soru seti işlemleri")
experiment_cli = typer.Typer(no_args_is_help=True, help="A/B öneri deneyleri")
app.add_typer(demo_cli, name="demo")
app.add_typer(golden_cli, name="golden")
app.add_typer(experiment_cli, name="experiment")
console = Console()


def _json_write(path: str | Path, value: Any) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _write_summary(path: str | Path, result: dict[str, Any], diagnosis: dict[str, Any] | None = None) -> Path:
    metrics = result.get("metrics", {})
    lines = ["# RAGnoz run summary", "", f"- Soru sayısı: {metrics.get('n', 0)}",
             f"- Retrieval sorusu: {metrics.get('retrieval_n', 0)}",
             f"- Accuracy: {metrics.get('accuracy', '—')}", "", "## Metrikler", "", "| Metrik | Değer |",
             "|---|---:|"]
    for key, value in metrics.items():
        if key not in {"attribution_counts", "missing_question_ids"} and isinstance(value, (int, float, str, type(None))):
            lines.append(f"| {key} | {'—' if value is None else value} |")
    if diagnosis:
        profile = diagnosis.get("profile", {})
        lines.extend(["", "## Mimari teşhisi", "", f"- Paradigma: {profile.get('paradigm', 'Undetermined')} (kalite puanı değildir)",
                      f"- Akış: {profile.get('flow', 'unknown')}", f"- Gözlem: {profile.get('observability', 'L0')}", "",
                      "## Bulgular", ""])
        for finding in diagnosis.get("findings", []):
            lines.append(f"- **{finding.get('id')} — {finding.get('title')}**: {finding.get('measured')}; eşik: {finding.get('threshold')}.")
        if not diagnosis.get("findings"):
            lines.append("- Ölçülen anti-pattern bulgusu yok.")
        lines.extend(["", "## Öneriler", ""])
        for rec in diagnosis.get("recommendations", []):
            lines.append(f"- **{rec.get('id')} [{rec.get('confidence')}] — {rec.get('target_module')}**: {rec.get('change')} Deney: `{rec.get('experiment', {}).get('type', 'A/B')}`.")
        if not diagnosis.get("recommendations"):
            lines.append("- Kanıta dayalı öneri yok.")
        lines.extend(["", "## Çıkarılamayanlar", ""])
        lines.extend(f"- {item}" for item in diagnosis.get("cannot_infer", []))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return target


def _read_traces(path: str | Path) -> list[QuestionTrace]:
    return import_jsonl(path)


def _load_adapter(specification: str) -> Any:
    source, separator, name = specification.rpartition(":")
    if not separator or not source or not name:
        raise typer.BadParameter("Adapter biçimi module:function veya /path/to/adapter.py:function olmalı")
    file_path = Path(source).expanduser()
    if file_path.is_file():
        module_spec = importlib.util.spec_from_file_location(f"ragnoz_user_adapter_{uuid.uuid4().hex[:8]}", file_path)
        if module_spec is None or module_spec.loader is None:
            raise typer.BadParameter(f"Adapter modülü yüklenemedi: {file_path}")
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_spec.name] = module
        parent = str(file_path.resolve().parent)
        sys.path.insert(0, parent)
        try:
            module_spec.loader.exec_module(module)
        finally:
            if sys.path and sys.path[0] == parent:
                sys.path.pop(0)
    else:
        module = importlib.import_module(source)
    factory = getattr(module, name, None)
    if not callable(factory):
        raise typer.BadParameter(f"Adapter factory bulunamadı: {specification}")
    adapter = factory()
    required = ("load_documents", "chunk", "index", "retrieve", "generate")
    missing = [method for method in required if not callable(getattr(adapter, method, None))]
    if missing:
        raise typer.BadParameter(f"Adapter eksik metod içeriyor: {', '.join(missing)}")
    return adapter


def _evaluate_adapter_instance(adapter: Any, items: list[Any], cache: StageCache, no_cache: bool,
                               run_id: str) -> tuple[list[QuestionTrace], dict[str, Any], dict[str, Any]]:
    runner = PipelineRunner(adapter, cache=cache, no_cache=no_cache)
    traces = runner.run(items)
    evaluated = evaluate(items, traces)
    description = _scrub(adapter.describe()) if callable(getattr(adapter, "describe", None)) else {}
    diagnosis = run_diagnosis(items, traces, [ItemEvaluation(**row) for row in evaluated["items"]],
                              description if isinstance(description, dict) else {}, run_id=run_id)
    diagnosis["cache"] = cache.stats()
    return traces, evaluated, diagnosis


def _scrub(value: Any) -> Any:
    secret_keys = {"api_key", "apikey", "token", "secret", "password", "authorization", "credential",
                   "credentials", "private_key", "client_secret", "access_token", "auth_token"}
    if isinstance(value, dict):
        def hidden(key: Any) -> bool:
            name = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
            return name in secret_keys or name.endswith(("_api_key", "_token", "_secret", "_password", "_credential"))
        return {str(key): "[REDACTED]" if hidden(key)
                else _scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, tuple):
        return [_scrub(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*\S+", r"\1=[REDACTED]", value)
        return re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", value)
    return value


def _print_metrics(metrics: dict[str, Any], title: str = "Evaluation") -> None:
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_column("n", justify="right")
    for name in ("accuracy", "hit@1", "hit@3", "hit@5", "hit@10", "mrr@5", "abstain_recall"):
        value = metrics.get(name)
        denominator = metrics.get("abstain_n", 0) if name.startswith("abstain_") else metrics.get("retrieval_n", 0) if name.startswith(("hit@", "mrr@")) else metrics.get("n", 0)
        table.add_row(name, "—" if value is None else f"{value:.3f}", str(denominator))
    console.print(table)
    if metrics.get("n", 0) < 30:
        console.print("[yellow]Uyarı: küçük örneklem (n < 30); aralıklar geniş olabilir.[/yellow]")
    counts = metrics.get("attribution_counts", {})
    if counts:
        console.print("Atıf:", ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))


@app.callback()
def main(version: bool = typer.Option(False, "--version", help="Sürümü göster ve çık.")) -> None:
    if version:
        from ragnoz import __version__
        console.print(f"RAGnoz {__version__}")
        raise typer.Exit()
