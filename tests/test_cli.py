from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ragnoz.cli import app
from ragnoz.demo import build_demo_traces, demo_path, load_demo_items
from ragnoz.importers import write_jsonl

runner = CliRunner()


def test_run_command_writes_trace_metrics_diagnosis_and_summary(tmp_path: Path):
    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps({"id": "Q1", "question": "Capital?", "expected_answer": "Paris",
                                  "evidence": [{"doc_id": "d1", "quote": "Paris is the capital of France."}]}) + "\n")
    adapter = tmp_path / "adapter.py"
    adapter.write_text('''
class Adapter:
    config = {"mode": "v1"}
    def load_documents(self): return [{"doc_id": "d1", "text": "Paris is the capital of France."}]
    def chunk(self, documents): return documents
    def index(self, chunks): return chunks
    def retrieve(self, question, index): return index
    def generate(self, question, context): return "Paris"
    def describe(self): return {"system": "test", "flow": "linear", "context_window_tokens": 1024}
    def fingerprint(self, stage): return self.config["mode"] if stage == "generate" else "stable"
def build(): return Adapter()
''', encoding="utf-8")
    output, cache = tmp_path / "runs", tmp_path / "cache"
    result = runner.invoke(app, ["run", "--golden", str(golden), "--adapter", f"{adapter}:build",
                                 "--output", str(output), "--cache-dir", str(cache)])
    assert result.exit_code == 0, result.output
    run_dir = next(output.iterdir())
    assert (run_dir / "traces.jsonl").exists()
    assert (run_dir / "results.jsonl").exists()
    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "diagnosis.json").exists()
    assert (run_dir / "summary.md").exists()
    assert json.loads((run_dir / "metrics.json").read_text())["accuracy"] == 1.0


def test_synthetic_demo_ab_does_not_raise_confidence_to_high(tmp_path: Path):
    items = load_demo_items()
    before, after = build_demo_traces("naive", items), build_demo_traces("advanced", items)
    before_path, after_path = tmp_path / "before.jsonl", tmp_path / "after.jsonl"
    write_jsonl(before, before_path)
    write_jsonl(after, after_path)
    output = tmp_path / "experiment.json"
    result = runner.invoke(app, ["experiment", "run", "rec-001", "--golden",
        str(demo_path() / "golden.jsonl"), "--before", str(before_path), "--after", str(after_path),
        "--output", str(output)])
    assert result.exit_code == 0, result.output
    record = json.loads(output.read_text())
    assert record["synthetic_or_demo_only"] is True
    assert record["status"] == "inconclusive"
    assert record["confidence_after_experiment"] == "medium"
