from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

from ragnoz.schemas import GoldenItem


def _normalize_quote(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).split())


def load_golden(path: str | Path) -> list[GoldenItem]:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() in {".jsonl", ".ndjson"}:
        raw: Any = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        raw = yaml.safe_load(text)
        if isinstance(raw, dict):
            raw = raw.get("items", raw.get("questions", []))
    if not isinstance(raw, list):
        raise TypeError("Altın seti bir kayıt listesi veya items alanı içermeli.")
    return [GoldenItem.model_validate(row) for row in raw]


def golden_hash(items: list[GoldenItem]) -> str:
    payload = [item.model_dump(mode="json", exclude_none=True) for item in items]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_golden(
    items: list[GoldenItem], corpus: dict[str, str] | None = None, fuzzy_threshold: float = 0.88
) -> list[str]:
    issues: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            issues.append(f"{item.id}: yinelenen ID")
        seen.add(item.id)
        if item.expected_behavior == "answer" and not item.expected_answer and not item.expected_values:
            issues.append(f"{item.id}: answer davranışı için expected_answer/expected_values eksik")
        if item.expected_behavior == "clarify" and not item.clarify_options:
            issues.append(f"{item.id}: clarify davranışı için clarify_options boş")
        for evidence in item.evidence:
            if corpus is None:
                continue
            page = corpus.get(evidence.doc_id)
            if page is None:
                issues.append(f"{item.id}: korpusta olmayan doc_id: {evidence.doc_id}")
                continue
            if evidence.quote and _normalize_quote(evidence.quote) not in _normalize_quote(page):
                from difflib import SequenceMatcher

                words = _normalize_quote(evidence.quote).split()
                haystack = _normalize_quote(page).split()
                found = False
                query = " ".join(words)
                for extra in (0, max(1, len(words) // 4)):
                    width = len(words) + extra
                    for start in range(max(1, len(haystack) - width + 1)):
                        candidate = " ".join(haystack[start : start + width])
                        if SequenceMatcher(None, query, candidate).ratio() >= fuzzy_threshold:
                            found = True
                            break
                    if found:
                        break
                if not found:
                    issues.append(f"{item.id}: kanıt alıntısı bulunamadı (eşik {fuzzy_threshold:.2f})")
            if evidence.page is None and evidence.char_start is None and evidence.quote is None:
                issues.append(f"{item.id}: kanıtın sayfa/aralık/alinti konumu belirtilmemiş")
    return issues


def load_corpus_json(path: str | Path) -> dict[str, str]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    return {str(p.get("doc_id", p.get("pageid", p.get("id")))): str(p.get("text", p.get("extract", ""))) for p in raw}
