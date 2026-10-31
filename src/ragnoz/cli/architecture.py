from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer
import yaml

from ragnoz.cli._shared import app, architecture_cli, console
from ragnoz.inspector import (
    NotADraftError,
    draft_to_architecture,
    inspect_adapter_source,
    inspection_to_draft,
)


@app.command("inspect")
def inspect_command(
    source: Path = typer.Argument(..., exists=True, readable=True, help="Taranacak adapter .py dosyası."),
    output: Path = typer.Option(Path("architecture.draft.yaml"), "--output", help="Yazılacak taslak dosyası."),
) -> None:
    """Adapter kaynak dosyasını statik olarak tara; dosya+satır kanıtlı bir TASLAK üret.

    Bu komut mimariyi ÇIKARMAZ, yalnız kodda ne BULUNDUĞUNU bildirir. Taslak, onaylanmadan
    `ragnoz diagnose`/`triage`/`report` tarafından ölçülmüş girdi sayılmaz.
    """
    result = inspect_adapter_source(source)
    draft = inspection_to_draft(result, datetime.now(UTC).isoformat())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(draft, allow_unicode=True, sort_keys=False), encoding="utf-8")
    console.print(f"{len(result.findings)} bulgu bulundu (dosya+satır kanıtlı): {output}")
    for item in result.findings:
        console.print(f"  {item.file}:{item.line} [{item.pattern}] {item.module}.{item.field} = {item.value}")
    if not result.findings:
        console.print("[yellow]Tanınan desen bulunamadı; mimari bilinmiyor olarak kalır.[/yellow]")
    console.print(f"Bu bir TASLAKTIR, ölçülmüş girdi değil. Onaylamak için: ragnoz architecture approve {output} "
                 "--output architecture.yaml")


@architecture_cli.command("approve")
def architecture_approve(
    draft: Path = typer.Argument(..., exists=True, readable=True, help="inspect ile üretilmiş taslak dosyası."),
    output: Path = typer.Option(Path("architecture.yaml"), "--output", help="Yazılacak onaylı mimari dosyası."),
) -> None:
    """Bir inspect taslağını, kullanıcı onayıyla, diagnose'un güvendiği mimari beyanına çevirir."""
    raw = yaml.safe_load(draft.read_text(encoding="utf-8")) or {}
    try:
        architecture = draft_to_architecture(raw if isinstance(raw, dict) else {})
    except NotADraftError as exc:
        console.print(f"[red]Onaylanamadı:[/red] {exc}")
        raise typer.Exit(1) from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(architecture, allow_unicode=True, sort_keys=False), encoding="utf-8")
    console.print(f"[green]Onaylandı:[/green] {draft} → {output}")
    console.print("Bundan sonra bu dosyadaki alanlar `ragnoz diagnose --architecture` için yüksek güvenli beyan sayılır.")
    for stage, fields in architecture.get("modules", {}).items():
        for subkey, values in fields.items():
            console.print(f"  modules.{stage}.{subkey}: {values}")
