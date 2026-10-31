from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml

from ragnoz.cli._shared import _print_metrics, console, demo_cli
from ragnoz.demo import (
    build_demo_traces,
    demo_path,
    initialize_demo,
    load_demo_items,
    seed_demo_traces,
)
from ragnoz.diagnosis import diagnose as run_diagnosis
from ragnoz.evaluation import evaluate
from ragnoz.schemas import ItemEvaluation


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
