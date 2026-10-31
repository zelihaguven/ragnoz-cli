from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ragnoz.cli import app
from ragnoz.demo import build_demo_traces, demo_path, load_demo_items
from ragnoz.importers import write_jsonl

runner = CliRunner()


def test_version_flag_prints_version_and_exits_without_requiring_a_subcommand():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    assert "RAGnoz" in result.output


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


def test_golden_quickstart_below_min_records_warns_about_low_confidence(tmp_path: Path):
    source = tmp_path / "qa.csv"
    source.write_text("question,answer\nQ1?,A1\nQ2?,A2\n", encoding="utf-8")
    output = tmp_path / "golden.jsonl"
    result = runner.invoke(app, ["golden", "quickstart", "--from", str(source), "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert "2 kayıt" in result.output
    normalized = " ".join(result.output.split())
    assert "Uyarı: 2 kayıt" in normalized
    assert "düşük güvenli" in normalized


def test_golden_quickstart_at_or_above_min_records_does_not_warn(tmp_path: Path):
    rows = "\n".join(f"Q{i}?,A{i}" for i in range(1, 6))
    source = tmp_path / "qa.csv"
    source.write_text("question,answer\n" + rows + "\n", encoding="utf-8")
    output = tmp_path / "golden.jsonl"
    result = runner.invoke(app, ["golden", "quickstart", "--from", str(source), "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert "5 kayıt" in result.output
    assert "Uyarı" not in result.output


def test_golden_quickstart_from_csv_writes_file_runs_validate_and_reports_line_errors(tmp_path: Path):
    source = tmp_path / "qa.csv"
    source.write_text("id,question,answer\nq-1,First question?,A\n,,Should be skipped\nq-1,Second question?,B\n")
    output = tmp_path / "golden.jsonl"
    result = runner.invoke(app, ["golden", "quickstart", "--from", str(source), "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert "satır 3:" in result.output
    assert "yinelenen ID" in result.output
    written = [json.loads(line) for line in output.read_text().splitlines()]
    assert [row["id"] for row in written] == ["q-1", "q-1"]


def test_triage_without_data_returns_guidance_panel_not_diagnose_vocabulary():
    result = runner.invoke(app, ["triage", "Cevaplar alakasız geliyor"])
    assert result.exit_code == 0, result.output
    assert "Yönlendirme" in result.output
    assert "ölçülmüş bulgu DEĞİL" in result.output
    assert "golden quickstart" in result.output
    assert "eşik" not in result.output
    assert "confidence" not in result.output.lower() or "[low]" not in result.output


def test_triage_with_data_filters_real_diagnosis_to_matching_rules(tmp_path: Path):
    items = load_demo_items()
    traces = build_demo_traces("broken", items)
    trace_path = tmp_path / "broken.jsonl"
    write_jsonl(traces, trace_path)
    architecture = demo_path() / "pipelines" / "broken.yaml"
    result = runner.invoke(app, ["triage", "Cevaplar alakasız geliyor", "--golden", str(demo_path() / "golden.jsonl"),
                                 "--traces", str(trace_path), "--architecture", str(architecture)])
    assert result.exit_code == 0, result.output
    assert "Eşleşen semptom(lar): irrelevant_answer" in result.output
    assert "AP-04" in result.output
    assert "AP-07" in result.output
    assert "AP-05" not in result.output


def test_golden_quickstart_reads_stdin_when_no_source_given(tmp_path: Path):
    output = tmp_path / "golden.jsonl"
    result = runner.invoke(app, ["golden", "quickstart", "--output", str(output)],
                           input="question,answer\nCapital of France?,Paris\n")
    assert result.exit_code == 0, result.output
    written = [json.loads(line) for line in output.read_text().splitlines()]
    assert written[0]["expected_answer"] == "Paris"
    assert "Sıradaki adım" in result.output


def test_golden_quickstart_empty_input_exits_nonzero(tmp_path: Path):
    output = tmp_path / "golden.jsonl"
    result = runner.invoke(app, ["golden", "quickstart", "--output", str(output)], input="")
    assert result.exit_code == 1
    assert "boş veya tanınmadı" in result.output
    assert not output.exists()


def test_golden_quickstart_all_rows_invalid_exits_nonzero(tmp_path: Path):
    source = tmp_path / "qa.csv"
    source.write_text("question,answer,type\nQ1?,A1,not-a-real-type\nQ2?,A2,also-bogus\n", encoding="utf-8")
    output = tmp_path / "golden.jsonl"
    result = runner.invoke(app, ["golden", "quickstart", "--from", str(source), "--output", str(output)])
    assert result.exit_code == 1, result.output
    assert "satır" in result.output
    assert "Hiçbir geçerli kayıt üretilemedi" in result.output


def test_golden_validate_happy_path_reports_count_and_hash(tmp_path: Path):
    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps({"id": "Q1", "question": "Capital?", "expected_answer": "Paris"}) + "\n", encoding="utf-8")
    result = runner.invoke(app, ["golden", "validate", str(golden)])
    assert result.exit_code == 0, result.output
    assert "1 kayıt" in result.output
    assert "SHA-256" in result.output


def test_golden_validate_reports_issues_and_exits_nonzero(tmp_path: Path):
    golden = tmp_path / "golden.jsonl"
    row = json.dumps({"id": "Q1", "question": "Capital?", "expected_answer": "Paris"})
    golden.write_text(row + "\n" + row + "\n", encoding="utf-8")
    result = runner.invoke(app, ["golden", "validate", str(golden)])
    assert result.exit_code == 1
    assert "yinelenen ID" in result.output


def test_golden_validate_unreadable_golden_exits_with_error_message(tmp_path: Path):
    golden = tmp_path / "golden.yaml"
    golden.write_text("just a plain string, not a list or mapping\n", encoding="utf-8")
    result = runner.invoke(app, ["golden", "validate", str(golden)])
    assert result.exit_code == 1
    assert "Altın seti okunamadı" in result.output


def test_triage_without_data_unmatched_complaint_shows_not_found_panel():
    result = runner.invoke(app, ["triage", "bugün hava çok güzel"])
    assert result.exit_code == 0, result.output
    assert "Yönlendirme bulunamadı" in result.output
    assert "golden quickstart" in result.output


def test_triage_with_empty_golden_and_traces_does_not_crash(tmp_path: Path):
    golden = tmp_path / "empty_golden.jsonl"
    traces = tmp_path / "empty_traces.jsonl"
    golden.write_text("", encoding="utf-8")
    traces.write_text("", encoding="utf-8")
    result = runner.invoke(app, ["triage", "cevaplar alakasız geliyor", "--golden", str(golden), "--traces", str(traces)])
    assert result.exit_code == 0, result.output
    assert "Eşleşen semptom(lar): irrelevant_answer" in result.output
    assert "eşleşen ölçülmüş bulgu yok" in result.output
