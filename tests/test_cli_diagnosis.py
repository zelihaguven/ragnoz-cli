from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from ragnoz.cli import app
from ragnoz.demo import build_demo_traces, demo_path, load_demo_items
from ragnoz.importers import write_jsonl

runner = CliRunner()


def test_report_command_writes_html_and_warns_without_redact(tmp_path: Path):
    items = load_demo_items()
    traces = build_demo_traces("broken", items)
    trace_path = tmp_path / "broken.jsonl"
    write_jsonl(traces, trace_path)
    output = tmp_path / "report.html"
    result = runner.invoke(app, ["report", "--traces", str(trace_path), "--golden", str(demo_path() / "golden.jsonl"),
                                 "--architecture", str(demo_path() / "pipelines" / "broken.yaml"), "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert output.exists()
    assert "<html" in output.read_text(encoding="utf-8").casefold()
    assert "--redact" in result.output


def test_diagnose_command_writes_json_and_prints_findings(tmp_path: Path):
    items = load_demo_items()
    traces = build_demo_traces("broken", items)
    trace_path = tmp_path / "broken.jsonl"
    write_jsonl(traces, trace_path)
    output = tmp_path / "diagnosis.json"
    result = runner.invoke(app, ["diagnose", "--traces", str(trace_path), "--golden", str(demo_path() / "golden.jsonl"),
                                 "--architecture", str(demo_path() / "pipelines" / "broken.yaml"), "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert output.exists()
    assert "Mimari:" in result.output
    assert "Tanı dosyası" in result.output


def test_report_command_with_redact_suppresses_warning(tmp_path: Path):
    items = load_demo_items()
    traces = build_demo_traces("naive", items)
    trace_path = tmp_path / "naive.jsonl"
    write_jsonl(traces, trace_path)
    output = tmp_path / "report.html"
    result = runner.invoke(app, ["report", "--traces", str(trace_path), "--golden", str(demo_path() / "golden.jsonl"),
                                 "--output", str(output), "--redact"])
    assert result.exit_code == 0, result.output
    assert "--redact" not in result.output
