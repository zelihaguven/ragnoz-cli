from __future__ import annotations

import json
from pathlib import Path

from ragnoz.corpus import download_revision_corpus, load_revision_manifest
from ragnoz.golden import load_golden
from ragnoz.schemas import GoldenItem, QuestionTrace, ScoredChunk

PACKAGE_DEMO = Path(__file__).parent / "data" / "demo"


def demo_path() -> Path:
    """Single source of truth for demo fixtures: the packaged `ragnoz.data.demo` directory.

    Ships inside the wheel (see `[tool.setuptools.package-data]` in pyproject.toml), so it is
    available identically whether RAGnoz is installed editable or from a built distribution.
    """
    return PACKAGE_DEMO


def load_demo_items() -> list[GoldenItem]:
    return load_golden(demo_path() / "golden.jsonl")


def _evidence_docs(item: GoldenItem) -> list[str]:
    return list(dict.fromkeys(ev.doc_id for ev in item.evidence))


def build_demo_traces(pipeline: str, items: list[GoldenItem] | None = None) -> list[QuestionTrace]:
    """Create deterministic, explicitly synthetic fixture traces for the three demo profiles."""
    if pipeline not in {"naive", "advanced", "broken"}:
        raise ValueError("pipeline naive, advanced veya broken olmalı")
    items = items or load_demo_items()
    traces: list[QuestionTrace] = []
    for index, item in enumerate(items):
        docs = _evidence_docs(item)
        doc_id = docs[0] if docs else "wiki-mini"
        quote = " … ".join(ev.quote for ev in item.evidence if ev.quote) if item.evidence else ""
        evidence = ScoredChunk(chunk_id=f"{item.id}-evidence", doc_id=doc_id, page=1,
                               text=quote or "Kayıtta beklenen kanıt bulunmuyor.", score=0.82, rank=1)
        decoy = ScoredChunk(chunk_id=f"{item.id}-decoy", doc_id="noise", page=1,
                            text="İlgisiz demo parçası.", score=0.71, rank=2)
        if pipeline == "advanced":
            is_correct = item.expected_behavior == "abstain" or index % 9 != 0
        elif pipeline == "naive":
            is_correct = item.expected_behavior != "abstain" and index % 3 != 0
        else:
            is_correct = item.expected_behavior != "abstain" and index % 4 == 1
            if item.lang == "en" and item.expected_behavior != "abstain":
                is_correct = False

        if item.expected_behavior == "abstain":
            abstained = pipeline == "advanced"
            answer_text = "" if abstained else "Korpus bunu desteklemiyor, ancak olası yanıt şudur."
            context: list[ScoredChunk] = []
            candidates: list[ScoredChunk] = []
            ranked: list[ScoredChunk] = []
        elif is_correct:
            abstained = False
            answer_text = item.expected_answer or (str(item.expected_values[0]) if item.expected_values else "")
            if pipeline == "advanced":
                candidates, ranked = [decoy, evidence], [evidence, decoy]
            else:
                candidates, ranked = [evidence, decoy], [evidence, decoy]
            context = ranked[:5]
        else:
            abstained = False
            if pipeline == "broken" and (index % 2 == 0 or item.lang == "en"):
                answer_text = "Bilgi bulunamadı."
                candidates, ranked, context = [decoy], [decoy], [decoy]
            elif item.type == "numeric" and item.expected_values:
                expected = str(item.expected_values[0].get("value")) if isinstance(item.expected_values[0], dict) else str(item.expected_values[0])
                answer_text = "8,488 m" if "8848" in expected else "1952"
                candidates, ranked, context = [evidence, decoy], [evidence, decoy], [evidence, decoy]
            else:
                answer_text = "The answer may be Mercury." if item.lang == "en" else "Yanıt Venüs olabilir."
                candidates, ranked, context = [evidence, decoy], [evidence, decoy], [evidence, decoy]
        traces.append(QuestionTrace.model_validate({
            "question_id": item.id, "question": item.question, "answer": {"text": answer_text, "abstained": abstained},
            "route": "abstained" if abstained else "answered", "candidates": candidates, "ranked": ranked,
            "context": context, "observability": "L3", "latency_ms": 8.0 + (index % 7) * 1.3, "seed": 19,
            "synthetic_fixture": True,
        }))
    return traces


def seed_demo_traces(destination: str | Path = ".ragnoz/demo-traces") -> dict[str, Path]:
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for pipeline in ("naive", "advanced", "broken"):
        path = target / f"{pipeline}.jsonl"
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            for trace in build_demo_traces(pipeline):
                stream.write(json.dumps(trace.model_dump(mode="json", exclude_none=True), ensure_ascii=False, sort_keys=True) + "\n")
        written[pipeline] = path
    return written


def initialize_demo(destination: str | Path = ".ragnoz/demo-corpus") -> Path:
    manifest = load_revision_manifest(demo_path() / "wiki-mini.revisions.json")
    return download_revision_corpus(manifest, destination)
