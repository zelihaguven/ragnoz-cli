"""Convert loose question/answer data (CSV, JSONL, markdown table) into GoldenItem rows.

Pure parsing/building logic, independent of the CLI, so it is testable on its own.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ragnoz.schemas import GoldenItem

_SEPARATOR_CELL = re.compile(r"^:?-+:?$")


@dataclass(frozen=True)
class ParsedRow:
    line: int
    raw: dict[str, Any] | None
    error: str | None = None


@dataclass(frozen=True)
class QuickstartResult:
    items: list[GoldenItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def detect_format(text: str, suffix: str | None = None) -> str:
    if suffix:
        normalized = suffix.lower().lstrip(".")
        if normalized in {"jsonl", "ndjson"}:
            return "jsonl"
        if normalized == "csv":
            return "csv"
        if normalized in {"md", "markdown"}:
            return "markdown"
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("{"):
            return "jsonl"
        if stripped.startswith("|"):
            return "markdown"
        break
    return "csv"


def _parse_csv(text: str) -> list[ParsedRow]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    headers = {name: name.strip().lower() for name in reader.fieldnames if name}
    rows: list[ParsedRow] = []
    for raw_row in reader:
        mapped = {headers.get(key, key): value for key, value in raw_row.items() if key}
        rows.append(ParsedRow(line=reader.line_num, raw=mapped))
    return rows


def _parse_markdown_table(text: str) -> list[ParsedRow]:
    header: list[str] | None = None
    rows: list[ParsedRow] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or "|" not in stripped:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if header is None:
            header = [cell.lower() for cell in cells]
            continue
        if all(_SEPARATOR_CELL.match(cell) for cell in cells):
            continue
        rows.append(ParsedRow(line=line_no, raw=dict(zip(header, cells))))
    return rows


def _parse_jsonl(text: str) -> list[ParsedRow]:
    rows: list[ParsedRow] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            data = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            rows.append(ParsedRow(line=line_no, raw=None, error=f"geçersiz JSON: {exc.msg}"))
            continue
        if not isinstance(data, dict):
            rows.append(ParsedRow(line=line_no, raw=None, error="JSON nesnesi (obje) bekleniyor"))
            continue
        rows.append(ParsedRow(line=line_no, raw=data))
    return rows


def parse_qa_text(text: str, fmt: str | None = None) -> list[ParsedRow]:
    resolved = fmt or detect_format(text)
    if resolved == "jsonl":
        return _parse_jsonl(text)
    if resolved == "markdown":
        return _parse_markdown_table(text)
    return _parse_csv(text)


def _next_id(index: int, seen: set[str]) -> str:
    bump = index
    candidate = f"q-{bump:03d}"
    while candidate in seen:
        bump += 1
        candidate = f"q-{bump:03d}"
    return candidate


def _split_tags(value: Any) -> list[str]:
    return [tag.strip() for tag in re.split(r"[|,]", str(value or "")) if tag.strip()]


def _normalize_row(raw: dict[str, Any], index: int, seen_ids: set[str]) -> dict[str, Any]:
    question = str(raw.get("question") or "").strip()
    answer = str(raw.get("expected_answer") or raw.get("answer") or "").strip()
    item_id = str(raw.get("id") or "").strip() or _next_id(index, seen_ids)
    seen_ids.add(item_id)
    behavior = str(raw.get("expected_behavior") or "").strip() or ("abstain" if not answer else "answer")
    lang = str(raw.get("lang") or "").strip() or "en"
    item_type = str(raw.get("type") or "").strip() or "factual"
    doc_id = str(raw.get("evidence_doc_id") or "").strip()
    quote = str(raw.get("evidence_quote") or "").strip()
    item: dict[str, Any] = {
        "id": item_id, "question": question, "lang": lang, "type": item_type,
        "tags": _split_tags(raw.get("tags")), "expected_behavior": behavior,
    }
    if answer:
        item["expected_answer"] = answer
    if doc_id:
        item["evidence"] = [{"doc_id": doc_id, "quote": quote or None}]
    return item


def _format_validation_error(exc: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}" for error in exc.errors()]
    return "; ".join(parts)


def build_golden_items(text: str, fmt: str | None = None) -> QuickstartResult:
    rows = parse_qa_text(text, fmt)
    seen_ids: set[str] = set()
    items: list[GoldenItem] = []
    errors: list[str] = []
    for index, row in enumerate(rows, start=1):
        if row.raw is None:
            errors.append(f"satır {row.line}: {row.error}")
            continue
        normalized = _normalize_row(row.raw, index, seen_ids)
        try:
            items.append(GoldenItem.model_validate(normalized))
        except ValidationError as exc:
            errors.append(f"satır {row.line}: {_format_validation_error(exc)}")
    return QuickstartResult(items=items, errors=errors)
