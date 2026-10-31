from __future__ import annotations

import importlib
import importlib.util
import json
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ragnoz.cache import StageCache
from ragnoz.compare import compare_evaluations
from ragnoz.demo import (
    build_demo_traces,
    demo_path,
    initialize_demo,
    load_demo_items,
    seed_demo_traces,
)
from ragnoz.diagnosis import diagnose as run_diagnosis
from ragnoz.diagnosis import (
    filter_diagnosis_by_complaint,
    guidance_for_complaint,
    load_architecture,
)
from ragnoz.evaluation import evaluate
from ragnoz.golden import golden_hash, load_corpus_json, load_golden, validate_golden
from ragnoz.golden_quickstart import build_golden_items
from ragnoz.importers import import_jsonl, write_jsonl
from ragnoz.reports import write_html
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


def _run_eval(golden_path: str | Path, trace_path: str | Path) -> tuple[list[Any], list[QuestionTrace], dict[str, Any]]:
    items = load_golden(golden_path)
    traces = _read_traces(trace_path)
    result = evaluate(items, traces)
    return items, traces, result


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


def _run_adapter(adapter_spec: str, golden: Path, cache_dir: Path, no_cache: bool) -> tuple[Any, list[QuestionTrace], dict[str, Any], dict[str, Any]]:
    adapter = _load_adapter(adapter_spec)
    items = load_golden(golden)
    traces, evaluated, diagnosis = _evaluate_adapter_instance(
        adapter, items, StageCache(cache_dir), no_cache, run_id=adapter_spec,
    )
    return items, traces, evaluated, diagnosis


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


@demo_cli.command("init")
def demo_init(destination: Path = typer.Option(Path(".ragnoz/demo-corpus"), "--destination", help="Corpus'un yerel indirme klasörü.")) -> None:
    """Sabit Wikipedia revision'larını yalnızca seçilen yerel klasöre indir."""
    try:
        output = initialize_demo(destination)
    except Exception as exc:
        console.print(f"[red]Demo corpus indirilemedi:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"Demo corpus yerel klasöre indirildi: {output}")
    console.print("Kaynak ve lisans bilgisi aynı klasördeki ATTRIBUTION.md dosyasındadır.")


@demo_cli.command("traces")
def demo_traces(output: Path = typer.Option(Path(".ragnoz/demo-traces"), "--output", help="Üç demo izinin yazılacağı klasör.")) -> None:
    written = seed_demo_traces(output)
    for name, path in written.items():
        console.print(f"{name}: {path}")
    console.print("Not: Bu izler deterministik tanıtım fikstürleridir; gerçek sistem ölçümü değildir.")


@demo_cli.command("run")
def demo_run(pipeline: str = typer.Option("all", "--pipeline", help="naive, advanced, broken veya all."), diagnose: bool = typer.Option(True, "--diagnose/--no-diagnose")) -> None:
    """Ağsız, sabit fikstürler üzerinde örnek değerlendirme ve teşhis çalıştır."""
    items = load_demo_items()
    if pipeline not in {"all", "naive", "advanced", "broken"}:
        raise typer.BadParameter("pipeline all, naive, advanced veya broken olmalı")
    names = ["naive", "advanced", "broken"] if pipeline == "all" else [pipeline]
    results: dict[str, dict[str, Any]] = {}
    for name in names:
        traces = build_demo_traces(name, items)
        evaluated = evaluate(items, traces)
        results[name] = evaluated
        _print_metrics(evaluated["metrics"], f"Demo: {name}")
        if diagnose:
            config_file = demo_path() / "pipelines" / f"{name}.yaml"
            config = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
            diagnosis = run_diagnosis(items, traces, [ItemEvaluation(**row) for row in evaluated["items"]], config, run_id=f"demo-{name}")
            findings = diagnosis["findings"]
            console.print(f"Paradigma: {diagnosis['profile']['paradigm']} · Akış: {diagnosis['profile']['flow']} · Gözlem: {diagnosis['profile']['observability']}")
            console.print("Bulgular:", ", ".join(f"{f['id']} ({f['title']})" for f in findings) if findings else "yok")
            if diagnosis["recommendations"]:
                console.print("Öneriler:")
                for rec in diagnosis["recommendations"]:
                    console.print(f"  {rec['id']} [{rec['confidence']}] {rec['target_module']}: {rec['change']} · deney={rec['experiment']['type']}")
    if len(names) > 1:
        console.print("\nBu fixture'lar örnek davranışları göstermek içindir; performans kıyası olarak yorumlanmamalıdır.")


@golden_cli.command("validate")
def golden_validate(path: Path = typer.Argument(..., exists=True, readable=True), corpus: Path | None = typer.Option(None, "--corpus", exists=True, readable=True)) -> None:
    try:
        items = load_golden(path)
        corpus_map = load_corpus_json(corpus) if corpus else None
        issues = validate_golden(items, corpus_map)
    except Exception as exc:
        console.print(f"[red]Altın seti okunamadı:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"{len(items)} kayıt · SHA-256 {golden_hash(items)}")
    if issues:
        for issue in issues:
            console.print(f"[red]• {issue}[/red]")
        raise typer.Exit(1)
    console.print("[green]Şema ve mevcut corpus kontrolleri geçti.[/green]")


@golden_cli.command("quickstart")
def golden_quickstart(
    source: Path | None = typer.Option(None, "--from", exists=True, readable=True,
                                       help="qa.csv / qa.jsonl / qa.md kaynağı. Verilmezse stdin okunur."),
    output: Path = typer.Option(Path("golden.jsonl"), "--output", help="Üretilecek altın set dosyası."),
    fmt: str | None = typer.Option(None, "--format", help="csv, jsonl veya markdown; verilmezse içerikten tahmin edilir."),
    corpus: Path | None = typer.Option(None, "--corpus", exists=True, readable=True, help="golden validate için opsiyonel korpus JSON'u."),
) -> None:
    """Gevşek soru-cevap verisinden (CSV/JSONL/markdown tablo) altın set üret ve doğrula."""
    text = source.read_text(encoding="utf-8") if source else sys.stdin.read()
    result = build_golden_items(text, fmt or (source.suffix.lstrip(".") if source else None))
    if not result.items and not result.errors:
        console.print("[red]Girdi boş veya tanınmadı.[/red]")
        raise typer.Exit(1)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for item in result.items:
            stream.write(json.dumps(item.model_dump(mode="json", exclude_none=True), ensure_ascii=False, sort_keys=True) + "\n")
    console.print(f"{len(result.items)} kayıt {output} dosyasına yazıldı.")
    if result.errors:
        console.print(f"[yellow]{len(result.errors)} satır atlandı:[/yellow]")
        for error in result.errors:
            console.print(f"  [red]•[/red] {error}")
    if not result.items:
        console.print("[red]Hiçbir geçerli kayıt üretilemedi.[/red]")
        raise typer.Exit(1)
    corpus_map = load_corpus_json(corpus) if corpus else None
    issues = validate_golden(result.items, corpus_map)
    if issues:
        console.print("[yellow]golden validate uyarıları:[/yellow]")
        for issue in issues:
            console.print(f"  [red]•[/red] {issue}")
    else:
        console.print("[green]golden validate: şema ve mevcut kontroller geçti.[/green]")
    console.print(f"Sıradaki adım: ragnoz run --golden {output} --adapter package.module:factory "
                 "(adapter'ın henüz yoksa: ragnoz import TRACES.jsonl --output .ragnoz/imported.jsonl)")


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


@app.command("diagnose")
def diagnose_command(traces: Path = typer.Option(..., "--traces", exists=True, readable=True), golden: Path = typer.Option(..., "--golden", exists=True, readable=True), architecture: Path | None = typer.Option(None, "--architecture", exists=True, readable=True), output: Path = typer.Option(Path(".ragnoz/diagnosis.json"), "--output")) -> None:
    items = load_golden(golden)
    trace_rows = _read_traces(traces)
    evaluated = evaluate(items, trace_rows)
    eval_models = [ItemEvaluation(**row) for row in evaluated["items"]]
    profile = load_architecture(architecture)
    result = run_diagnosis(items, trace_rows, eval_models, profile, run_id=traces.stem)
    _json_write(output, result)
    console.print(f"Mimari: {result['profile']['paradigm']} · akış: {result['profile']['flow']} · gözlem: {result['profile']['observability']}")
    console.print(f"Bulgular: {len(result['findings'])} · öneriler: {len(result['recommendations'])}")
    for finding in result["findings"]:
        console.print(f"{finding['id']} {finding['title']} — {finding['measured']} (eşik {finding['threshold']})")
    for rec in result["recommendations"]:
        console.print(f"{rec['id']} [{rec['confidence']}] {rec['target_module']}: {rec['change']}")
    console.print(f"Tanı dosyası: {output}")


@app.command("triage")
def triage_command(
    complaint: str = typer.Argument(..., help="Derdini kendi kelimelerinle anlat (ör. 'cevaplar alakasız geliyor')."),
    golden: Path | None = typer.Option(None, "--golden", exists=True, readable=True),
    traces: Path | None = typer.Option(None, "--traces", exists=True, readable=True),
    architecture: Path | None = typer.Option(None, "--architecture", exists=True, readable=True),
) -> None:
    """Doğal dil şikayetten yönlendirme üret; golden+traces varsa gerçek bulguları filtrele."""
    if golden and traces:
        items = load_golden(golden)
        trace_rows = _read_traces(traces)
        evaluated = evaluate(items, trace_rows)
        eval_models = [ItemEvaluation(**row) for row in evaluated["items"]]
        result = run_diagnosis(items, trace_rows, eval_models, load_architecture(architecture), run_id=traces.stem)
        filtered = filter_diagnosis_by_complaint(complaint, result)
        console.print(f"Eşleşen semptom(lar): {', '.join(filtered['matched_symptoms']) or 'yok'}")
        if not filtered["findings"]:
            console.print("[yellow]Bu şikayetle eşleşen ölçülmüş bulgu yok.[/yellow] Tüm bulgular için: ragnoz diagnose")
            return
        console.print("Bu şikayetle ilişkili, ölçülmüş bulgular (tam diagnose çıktısından filtrelendi):")
        for finding in filtered["findings"]:
            console.print(f"  {finding['id']} {finding['title']} — {finding['measured']} (eşik {finding['threshold']})")
        for rec in filtered["recommendations"]:
            console.print(f"  → {rec['id']} [{rec['confidence']}] {rec['target_module']}: {rec['change']}")
        return
    guidance = guidance_for_complaint(complaint, has_golden=bool(golden))
    if not guidance:
        console.print(Panel(
            "Bu şikayeti tanınan semptomlarla eşleştiremedim.\n"
            "Sıradaki adım: ragnoz golden quickstart --from qa.csv, sonra ragnoz run / ragnoz diagnose.",
            title="Yönlendirme bulunamadı", border_style="yellow"))
        return
    lines = []
    for item in guidance:
        lines.append(f"[bold]{item.symptom}[/bold]\n  Bak: {item.module}  ·  kurallar: {', '.join(item.rule_ids) or '—'}\n  Sıradaki adım: {item.next_command}")
    console.print(Panel("\n\n".join(lines), title="Yönlendirme (ölçülmüş bulgu DEĞİL — ne yapman gerektiğini söylemez)",
                        subtitle="Gerçek, kanıtlı teşhis için: ragnoz diagnose", border_style="yellow"))


@app.command("report")
def report_command(traces: Path = typer.Option(..., "--traces", exists=True, readable=True), golden: Path = typer.Option(..., "--golden", exists=True, readable=True), architecture: Path | None = typer.Option(None, "--architecture", exists=True, readable=True), output: Path = typer.Option(Path(".ragnoz/report.html"), "--output"), redact: bool = typer.Option(False, "--redact", help="Soru/cevap metinlerini ve olası tanımlayıcıları maskele.")) -> None:
    items = load_golden(golden)
    trace_rows = _read_traces(traces)
    result = evaluate(items, trace_rows)
    eval_models = [ItemEvaluation(**row) for row in result["items"]]
    diagnosis = run_diagnosis(items, trace_rows, eval_models, load_architecture(architecture), run_id=traces.stem)
    write_html(output, result, diagnosis, redact=redact)
    console.print(f"Tek dosyalı çevrimdışı HTML rapor yazıldı: {output}")
    if not redact:
        console.print("[yellow]Bu rapor soru/cevap metni içerebilir; paylaşmadan önce --redact kullanın veya içeriği inceleyin.[/yellow]")


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


if __name__ == "__main__":
    app()
