from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ragnoz.cli import app
from ragnoz.demo import build_demo_traces, load_demo_items
from ragnoz.importers import write_jsonl

runner = CliRunner()


def _write_golden(tmp_path: Path) -> Path:
    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps({"id": "Q1", "question": "Capital?", "expected_answer": "Paris",
                                  "evidence": [{"doc_id": "d1", "quote": "Paris is the capital of France."}]}) + "\n",
                      encoding="utf-8")
    return golden


def test_import_traces_round_trips_jsonl(tmp_path: Path):
    items = load_demo_items()
    traces = build_demo_traces("naive", items)
    source = tmp_path / "source.jsonl"
    write_jsonl(traces, source)
    output = tmp_path / "imported.jsonl"
    result = runner.invoke(app, ["import", str(source), "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert output.exists()
    assert "iz içe aktarıldı" in result.output


def test_evaluate_command_writes_run_artifacts(tmp_path: Path):
    items = load_demo_items()
    traces = build_demo_traces("advanced", items)
    trace_path = tmp_path / "advanced.jsonl"
    write_jsonl(traces, trace_path)
    output = tmp_path / "runs"
    result = runner.invoke(app, ["eval", "--golden", _golden_for_demo().as_posix(), "--traces", str(trace_path), "--output", str(output)])
    assert result.exit_code == 0, result.output
    run_dir = next(output.iterdir())
    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "results.jsonl").exists()
    assert (run_dir / "summary.md").exists()


def _golden_for_demo() -> Path:
    from ragnoz.demo import demo_path
    return demo_path() / "golden.jsonl"


def test_run_command_reports_error_and_exits_on_adapter_failure(tmp_path: Path):
    golden = _write_golden(tmp_path)
    adapter_path = tmp_path / "broken_adapter.py"
    adapter_path.write_text('''
class Adapter:
    def load_documents(self): raise RuntimeError("boom")
    def chunk(self, documents): return documents
    def index(self, chunks): return chunks
    def retrieve(self, question, index): return index
    def generate(self, question, context): return "Paris"
def build(): return Adapter()
''', encoding="utf-8")
    result = runner.invoke(app, ["run", "--golden", str(golden), "--adapter", f"{adapter_path}:build"])
    assert result.exit_code == 1
    assert "Adapter çalıştırılamadı" in result.output


def test_compare_command_writes_comparison_and_prints_tables(tmp_path: Path):
    items = load_demo_items()
    before = build_demo_traces("naive", items)
    after = build_demo_traces("advanced", items)
    before_path, after_path = tmp_path / "before.jsonl", tmp_path / "after.jsonl"
    write_jsonl(before, before_path)
    write_jsonl(after, after_path)
    output = tmp_path / "compare.json"
    result = runner.invoke(app, ["compare", "--before", str(before_path), "--after", str(after_path),
                                 "--golden", _golden_for_demo().as_posix(), "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert output.exists()
    assert "Soru geçişleri" in result.output
