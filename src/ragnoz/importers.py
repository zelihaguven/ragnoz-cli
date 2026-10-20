from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ragnoz.schemas import QuestionTrace


def _path(obj: Any, expression: str | None, default: Any = None) -> Any:
    if not expression:
        return default
    cur = obj
    for part in expression.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return default
    return cur if cur is not None else default


def _chunks(value: Any, mapping: dict[str, str] | None = None) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    mapping = mapping or {}
    chunks: list[dict[str, Any]] = []
    for index, row in enumerate(value):
        if isinstance(row, str):
            chunks.append({"doc_id": f"unknown-{index}", "text": row, "rank": index + 1})
        elif isinstance(row, dict):
            chunks.append(
                {
                    "doc_id": _path(row, mapping.get("doc_id", "doc_id"), f"unknown-{index}"),
                    "page": _path(row, mapping.get("page", "page")),
                    "text": _path(row, mapping.get("text", "text"), ""),
                    "score": _path(row, mapping.get("score", "score")),
                    "rank": _path(row, mapping.get("rank", "rank"), index + 1),
                    "chunk_id": _path(row, mapping.get("chunk_id", "chunk_id")),
                    "char_start": _path(row, mapping.get("char_start", "char_start")),
                    "char_end": _path(row, mapping.get("char_end", "char_end")),
                }
            )
    return chunks


def import_jsonl(path: str | Path, mapping_path: str | Path | None = None) -> list[QuestionTrace]:
    mapping: dict[str, Any] = {}
    if mapping_path:
        mapping = json.loads(Path(mapping_path).read_text(encoding="utf-8"))
    chunk_map = mapping.get("chunks", {})
    results: list[QuestionTrace] = []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        qid = _path(row, mapping.get("question_id"), row.get("question_id", row.get("id")))
        question = _path(row, mapping.get("question"), row.get("question"))
        answer = _path(row, mapping.get("answer"), row.get("answer"))
        if not qid:
            if not question:
                raise ValueError(f"Satır {line_no}: question_id veya question gerekli")
            qid = f"import-{line_no:04d}"
        candidates = _chunks(_path(row, mapping.get("candidates", "candidates"), row.get("retrieved_chunks", [])), chunk_map)
        ranked = _chunks(_path(row, mapping.get("ranked", "ranked"), row.get("reranked_chunks", candidates)), chunk_map)
        context = _chunks(_path(row, mapping.get("context", "context"), row.get("context_chunks", row.get("retrieved_chunks", []))), chunk_map)
        if isinstance(answer, dict) and mapping.get("answer_text"):
            answer = _path(answer, mapping["answer_text"], "")
        results.append(
            QuestionTrace.model_validate({
                "question_id": str(qid),
                "question": question,
                "answer": answer if isinstance(answer, (dict, str)) else str(answer or ""),
                "route": "error" if row.get("error") else row.get("route", "answered"),
                "candidates": candidates,
                "ranked": ranked,
                "context": context,
                "latency_ms": row.get("latency_ms"),
                "error": row.get("error"),
                "observability": row.get("observability"),
                "query_variants": row.get("query_variants", []),
                "retrieval_rounds": row.get("retrieval_rounds"),
                "route_label": row.get("route_label"),
                "memory_used": row.get("memory_used"),
                "seed": row.get("seed"),
                "synthetic_fixture": row.get("synthetic_fixture", False),
            })
        )
    return results


def write_jsonl(traces: list[QuestionTrace], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        for trace in traces:
            stream.write(json.dumps(trace.model_dump(mode="json", exclude_none=True), ensure_ascii=False, sort_keys=True) + "\n")
