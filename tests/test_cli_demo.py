from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from ragnoz import corpus as corpus_module
from ragnoz.cli import app

runner = CliRunner()
_RealClient = httpx.Client


def _patch_wiki_transport(monkeypatch: pytest.MonkeyPatch, status_code: int = 200) -> None:
    html = f"<html><body><p>{'A' * 150}</p></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=html if status_code == 200 else None)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(corpus_module.httpx, "Client",
                        lambda *args, **kwargs: _RealClient(*args, **{**kwargs, "transport": transport}))
    monkeypatch.setattr(corpus_module.time, "sleep", lambda seconds: None)


def test_demo_init_downloads_corpus_to_destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_wiki_transport(monkeypatch, status_code=200)
    destination = tmp_path / "demo-corpus"
    result = runner.invoke(app, ["demo", "init", "--destination", str(destination)])
    assert result.exit_code == 0, result.output
    assert (destination / "pages.json").exists()
    assert (destination / "ATTRIBUTION.md").exists()
    assert "indirildi" in result.output


def test_demo_init_reports_error_and_exits_on_download_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_wiki_transport(monkeypatch, status_code=404)
    destination = tmp_path / "demo-corpus"
    result = runner.invoke(app, ["demo", "init", "--destination", str(destination)])
    assert result.exit_code == 1
    assert "Demo corpus indirilemedi" in result.output


def test_demo_traces_writes_three_pipeline_fixture_files(tmp_path: Path):
    output = tmp_path / "demo-traces"
    result = runner.invoke(app, ["demo", "traces", "--output", str(output)])
    assert result.exit_code == 0, result.output
    for name in ("naive", "advanced", "broken"):
        assert (output / f"{name}.jsonl").exists()
    assert "deterministik" in result.output


def test_demo_run_single_pipeline_with_diagnosis():
    result = runner.invoke(app, ["demo", "run", "--pipeline", "broken"])
    assert result.exit_code == 0, result.output
    assert "Paradigma" in result.output
    assert "Demo: broken" in result.output


def test_demo_run_without_diagnosis_flag():
    result = runner.invoke(app, ["demo", "run", "--pipeline", "naive", "--no-diagnose"])
    assert result.exit_code == 0, result.output
    assert "Paradigma" not in result.output


def test_demo_run_rejects_unknown_pipeline():
    result = runner.invoke(app, ["demo", "run", "--pipeline", "nonsense"])
    assert result.exit_code != 0


def test_demo_run_all_prints_disclaimer():
    result = runner.invoke(app, ["demo", "run", "--pipeline", "all"])
    assert result.exit_code == 0, result.output
    collapsed = " ".join(result.output.split())
    assert "performans kıyası olarak yorumlanmamalıdır" in collapsed
