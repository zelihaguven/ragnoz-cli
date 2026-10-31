from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from ragnoz.cli import app
from ragnoz.demo import build_demo_traces, demo_path, load_demo_items
from ragnoz.importers import write_jsonl

runner = CliRunner()

_ADAPTER_WITH_PATTERNS = '''
class Adapter:
    def __init__(self):
        self.config = {"top_k": 7, "chunk_size": 256}
    def chunk(self, documents): return documents
    def rerank(self, question, candidates): return candidates
'''

_ADAPTER_WITHOUT_PATTERNS = '''
class Adapter:
    def chunk(self, documents): return documents
'''


def test_inspect_writes_draft_and_lists_findings(tmp_path: Path):
    adapter = tmp_path / "adapter.py"
    adapter.write_text(_ADAPTER_WITH_PATTERNS, encoding="utf-8")
    output = tmp_path / "architecture.draft.yaml"
    result = runner.invoke(app, ["inspect", str(adapter), "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert output.exists()
    draft = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert draft["inspected_draft"] is True
    assert "bulgu bulundu" in result.output
    assert "TASLAKTIR" in result.output


def test_inspect_warns_when_nothing_recognized(tmp_path: Path):
    adapter = tmp_path / "adapter.py"
    adapter.write_text(_ADAPTER_WITHOUT_PATTERNS, encoding="utf-8")
    output = tmp_path / "architecture.draft.yaml"
    result = runner.invoke(app, ["inspect", str(adapter), "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert "Tanınan desen bulunamadı" in result.output


def test_architecture_approve_writes_architecture_yaml(tmp_path: Path):
    adapter = tmp_path / "adapter.py"
    adapter.write_text(_ADAPTER_WITH_PATTERNS, encoding="utf-8")
    draft = tmp_path / "architecture.draft.yaml"
    runner.invoke(app, ["inspect", str(adapter), "--output", str(draft)])
    output = tmp_path / "architecture.yaml"
    result = runner.invoke(app, ["architecture", "approve", str(draft), "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert output.exists()
    architecture = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert "modules" in architecture
    assert "inspected_draft" not in architecture
    assert "Onaylandı" in result.output


def test_architecture_approve_rejects_non_draft_file(tmp_path: Path):
    not_a_draft = tmp_path / "plain.yaml"
    not_a_draft.write_text(yaml.safe_dump({"modules": {"retrieval": {}}}), encoding="utf-8")
    output = tmp_path / "architecture.yaml"
    result = runner.invoke(app, ["architecture", "approve", str(not_a_draft), "--output", str(output)])
    assert result.exit_code == 1
    assert "Onaylanamadı" in result.output
    assert not output.exists()


def test_diagnose_refuses_unapproved_draft(tmp_path: Path):
    adapter = tmp_path / "adapter.py"
    adapter.write_text(_ADAPTER_WITH_PATTERNS, encoding="utf-8")
    draft = tmp_path / "architecture.draft.yaml"
    runner.invoke(app, ["inspect", str(adapter), "--output", str(draft)])

    items = load_demo_items()
    traces = build_demo_traces("broken", items)
    trace_path = tmp_path / "broken.jsonl"
    write_jsonl(traces, trace_path)

    result = runner.invoke(app, ["diagnose", "--golden", str(demo_path() / "golden.jsonl"),
                                 "--traces", str(trace_path), "--architecture", str(draft)])
    assert result.exit_code == 1
    assert "Mimari dosyası kullanılamadı" in result.output
    assert "architecture approve" in result.output


def test_diagnose_accepts_approved_architecture_end_to_end(tmp_path: Path):
    adapter = tmp_path / "adapter.py"
    adapter.write_text(_ADAPTER_WITH_PATTERNS, encoding="utf-8")
    draft = tmp_path / "architecture.draft.yaml"
    runner.invoke(app, ["inspect", str(adapter), "--output", str(draft)])
    approved = tmp_path / "architecture.yaml"
    approve_result = runner.invoke(app, ["architecture", "approve", str(draft), "--output", str(approved)])
    assert approve_result.exit_code == 0, approve_result.output

    items = load_demo_items()
    traces = build_demo_traces("broken", items)
    trace_path = tmp_path / "broken.jsonl"
    write_jsonl(traces, trace_path)
    diagnosis_output = tmp_path / "diagnosis.json"

    result = runner.invoke(app, ["diagnose", "--golden", str(demo_path() / "golden.jsonl"),
                                 "--traces", str(trace_path), "--architecture", str(approved),
                                 "--output", str(diagnosis_output)])
    assert result.exit_code == 0, result.output
    record = json.loads(diagnosis_output.read_text())
    assert record["profile"] is not None
