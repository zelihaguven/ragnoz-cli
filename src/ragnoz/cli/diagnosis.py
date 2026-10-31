from __future__ import annotations

from pathlib import Path

import typer
from rich.panel import Panel

from ragnoz.cli._shared import _json_write, _read_traces, app, console
from ragnoz.diagnosis import diagnose as run_diagnosis
from ragnoz.diagnosis import (
    filter_diagnosis_by_complaint,
    guidance_for_complaint,
    load_architecture,
)
from ragnoz.evaluation import evaluate
from ragnoz.golden import load_golden
from ragnoz.reports import write_html
from ragnoz.schemas import ItemEvaluation


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
