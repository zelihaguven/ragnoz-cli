from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from ragnoz.cli._shared import console, golden_cli
from ragnoz.golden import golden_hash, load_corpus_json, load_golden, validate_golden
from ragnoz.golden_quickstart import build_golden_items

MIN_RECOMMENDED_RECORDS = 5


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
    if 0 < len(result.items) < MIN_RECOMMENDED_RECORDS:
        console.print(
            f"[yellow]Uyarı: {len(result.items)} kayıt, önerilen alt sınırın (≥{MIN_RECOMMENDED_RECORDS}) altında.[/yellow] "
            "Bu boyutta ölçümler düşük güvenli kalır (n küçükken Wilson/McNemar aralıkları geniş olur); "
            "mümkünse en az 5-10 soru-cevap ekleyin."
        )
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
