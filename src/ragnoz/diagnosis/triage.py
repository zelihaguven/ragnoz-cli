"""Natural-language complaint -> rule pointer bridge.

Two tiers:
- No golden/traces yet: `guidance_for_complaint` returns `Guidance` rows — keyword-based,
  unverified, and type-restricted to "where to look", never "what to fix".
- Golden+traces already available: `filter_diagnosis_by_complaint` narrows a real
  `diagnose()` result down to the findings/recommendations relevant to the complaint;
  those keep their full, measured shape since they are evidence-backed.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

from ragnoz.diagnosis.engine import _rule, rules_by_symptom
from ragnoz.schemas import Guidance

SYMPTOMS_DIR = Path(__file__).resolve().parent.parent / "data" / "symptoms"

NEXT_COMMAND_NO_GOLDEN = "ragnoz golden quickstart --from qa.csv (en az 5-10 soru-cevap)"
NEXT_COMMAND_WITH_GOLDEN = "ragnoz run --golden GOLDEN.jsonl --adapter package.module:factory"

# Python's default .casefold() maps ASCII "I" -> "i" (dotted), but Turkish uppercase "I"
# is the dotless "ı", not "i". Without this, "ALAKASIZ" would never match "alakasız".
_TURKISH_UPPER_MAP = str.maketrans({"İ": "i", "I": "ı"})


def _normalize_tr(text: str) -> str:
    return text.translate(_TURKISH_UPPER_MAP).casefold()


@functools.cache
def _symptom_catalog() -> dict[str, Any]:
    return yaml.safe_load((SYMPTOMS_DIR / "catalog.yaml").read_text(encoding="utf-8")) or {}


def match_symptoms(complaint: str) -> list[str]:
    normalized = _normalize_tr(complaint)
    return [symptom_id for symptom_id, spec in _symptom_catalog().items()
            if any(_normalize_tr(keyword) in normalized for keyword in spec.get("keywords", []))]


def guidance_for_complaint(complaint: str, has_golden: bool = False) -> list[Guidance]:
    catalog = _symptom_catalog()
    by_symptom = rules_by_symptom()
    next_command = NEXT_COMMAND_WITH_GOLDEN if has_golden else NEXT_COMMAND_NO_GOLDEN
    guidance: list[Guidance] = []
    for symptom_id in match_symptoms(complaint):
        rule_ids = by_symptom.get(symptom_id, [])
        modules = sorted({_rule(rule_id)["module"] for rule_id in rule_ids})
        guidance.append(Guidance(
            symptom=catalog[symptom_id].get("label", symptom_id),
            module=", ".join(modules) if modules else "bilinmiyor",
            rule_ids=rule_ids,
            next_command=next_command,
        ))
    return guidance


def filter_diagnosis_by_complaint(complaint: str, diagnosis: dict[str, Any]) -> dict[str, Any]:
    by_symptom = rules_by_symptom()
    matched_symptoms = match_symptoms(complaint)
    relevant_rules = {rule_id for symptom_id in matched_symptoms for rule_id in by_symptom.get(symptom_id, [])}
    return {
        **diagnosis,
        "matched_symptoms": matched_symptoms,
        "findings": [f for f in diagnosis.get("findings", []) if f["id"] in relevant_rules],
        "recommendations": [r for r in diagnosis.get("recommendations", []) if r["rule_id"] in relevant_rules],
    }
