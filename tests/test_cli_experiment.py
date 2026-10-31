from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ragnoz.cli import app
from ragnoz.demo import build_demo_traces, load_demo_items
from ragnoz.importers import write_jsonl

runner = CliRunner()

_BARE_ADAPTER = '''
class Adapter:
    config = {"mode": "v1"}
    def load_documents(self): return [{"doc_id": "d1", "text": "Paris is the capital of France."}]
    def chunk(self, documents): return documents
    def index(self, chunks): return chunks
    def retrieve(self, question, index): return index
    def generate(self, question, context): return "Paris"
    def describe(self): return {"system": "test", "flow": "linear", "context_window_tokens": 1024}
    def fingerprint(self, stage): return "stable"
def build(): return Adapter()
'''

_HOOKED_ADAPTER = '''
class Adapter:
    config = {"mode": "v1"}
    def __init__(self, mode="v1"):
        self.mode = mode
    def load_documents(self): return [{"doc_id": "d1", "text": "Paris is the capital of France."}]
    def chunk(self, documents): return documents
    def index(self, chunks): return chunks
    def retrieve(self, question, index): return index
    def generate(self, question, context): return "Paris" if self.mode == "v1" else "Berlin"
    def describe(self): return {"system": "test", "flow": "linear", "context_window_tokens": 1024}
    def fingerprint(self, stage): return self.mode if stage == "generate" else "stable"
    def with_ablation(self, ablation, module): return Adapter(mode="v2")
    def with_experiment(self, recommendation_id): return Adapter(mode="v2")
def build(): return Adapter()
'''


def _write_golden(tmp_path: Path) -> Path:
    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps({"id": "Q1", "question": "Capital?", "expected_answer": "Paris",
                                  "evidence": [{"doc_id": "d1", "quote": "Paris is the capital of France."}]}) + "\n",
                      encoding="utf-8")
    return golden


def test_ablate_without_adapter_or_traces_writes_draft(tmp_path: Path):
    output = tmp_path / "ablation.json"
    result = runner.invoke(app, ["ablate", "--type", "remove", "--module", "retrieval", "--output", str(output)])
    assert result.exit_code == 0, result.output
    record = json.loads(output.read_text())
    assert record["executed"] is False
    assert record["status"] == "inconclusive"
    assert "taslak" in result.output


def test_ablate_rejects_unknown_type():
    result = runner.invoke(app, ["ablate", "--type", "bogus", "--module", "retrieval"])
    assert result.exit_code != 0


def test_ablate_with_traces_only_records_trace_count(tmp_path: Path):
    items = load_demo_items()
    traces = build_demo_traces("naive", items)
    trace_path = tmp_path / "naive.jsonl"
    write_jsonl(traces, trace_path)
    output = tmp_path / "ablation.json"
    result = runner.invoke(app, ["ablate", "--type", "swap", "--module", "chunking",
                                 "--traces", str(trace_path), "--output", str(output)])
    assert result.exit_code == 0, result.output
    record = json.loads(output.read_text())
    assert record["trace_count"] == len(traces)
    assert record["executed"] is False


def test_ablate_with_adapter_requires_golden(tmp_path: Path):
    adapter_path = tmp_path / "adapter.py"
    adapter_path.write_text(_BARE_ADAPTER, encoding="utf-8")
    result = runner.invoke(app, ["ablate", "--type", "remove", "--module", "retrieval",
                                 "--adapter", f"{adapter_path}:build"])
    assert result.exit_code != 0


def test_ablate_with_adapter_lacking_hook_leaves_draft_reason(tmp_path: Path):
    adapter_path = tmp_path / "adapter.py"
    adapter_path.write_text(_BARE_ADAPTER, encoding="utf-8")
    golden = _write_golden(tmp_path)
    output = tmp_path / "ablation.json"
    result = runner.invoke(app, ["ablate", "--type", "remove", "--module", "retrieval",
                                 "--adapter", f"{adapter_path}:build", "--golden", str(golden), "--output", str(output)])
    assert result.exit_code == 0, result.output
    record = json.loads(output.read_text())
    assert record["executed"] is False
    assert "with_ablation" in record["reason"]


def test_ablate_with_adapter_hook_executes_and_compares(tmp_path: Path):
    adapter_path = tmp_path / "adapter.py"
    adapter_path.write_text(_HOOKED_ADAPTER, encoding="utf-8")
    golden = _write_golden(tmp_path)
    output = tmp_path / "ablation.json"
    result = runner.invoke(app, ["ablate", "--type", "remove", "--module", "generation",
                                 "--adapter", f"{adapter_path}:build", "--golden", str(golden), "--output", str(output)])
    assert result.exit_code == 0, result.output
    record = json.loads(output.read_text())
    assert record["executed"] is True
    assert "comparison" in record


def test_experiment_run_requires_golden():
    result = runner.invoke(app, ["experiment", "run", "rec-001"])
    assert result.exit_code != 0


def test_experiment_run_requires_adapter_or_before_after(tmp_path: Path):
    golden = _write_golden(tmp_path)
    result = runner.invoke(app, ["experiment", "run", "rec-001", "--golden", str(golden)])
    assert result.exit_code != 0


def test_experiment_run_with_adapter_lacking_hook_is_inconclusive(tmp_path: Path):
    adapter_path = tmp_path / "adapter.py"
    adapter_path.write_text(_BARE_ADAPTER, encoding="utf-8")
    golden = _write_golden(tmp_path)
    output = tmp_path / "experiment.json"
    result = runner.invoke(app, ["experiment", "run", "rec-001", "--golden", str(golden),
                                 "--adapter", f"{adapter_path}:build", "--output", str(output)])
    assert result.exit_code == 0, result.output
    record = json.loads(output.read_text())
    assert record["executed"] is False
    assert record["status"] == "inconclusive"


def test_experiment_run_with_adapter_hook_executes(tmp_path: Path):
    adapter_path = tmp_path / "adapter.py"
    adapter_path.write_text(_HOOKED_ADAPTER, encoding="utf-8")
    golden = _write_golden(tmp_path)
    output = tmp_path / "experiment.json"
    result = runner.invoke(app, ["experiment", "run", "rec-001", "--golden", str(golden),
                                 "--adapter", f"{adapter_path}:build", "--output", str(output)])
    assert result.exit_code == 0, result.output
    record = json.loads(output.read_text())
    assert record["executed"] is True
    assert "comparison" in record
