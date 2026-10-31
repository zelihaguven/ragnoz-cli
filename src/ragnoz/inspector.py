"""Static source scanner for adapter files.

Reports only what pattern-matching over the AST literally finds — a dict-literal key, an
import, a method definition — each with file+line evidence. It never infers architecture,
quality, or behavior from what it finds; that interpretation step belongs to the user, via
`ragnoz architecture approve`, not to this module.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DICT_KEY_MODULES: dict[str, str] = {
    "top_k": "retrieval",
    "chunk_size": "indexing.chunking",
    "overlap": "indexing.chunking",
    "chunk_overlap": "indexing.chunking",
    "window": "context",
    "context_window": "context",
    "context_window_tokens": "context",
    "max_tokens": "context",
    "temperature": "generation",
    "retriever": "retrieval",
    "generator": "generation",
    "reranker": "post_retrieval.rerank",
    "rerank": "post_retrieval.rerank",
    "cross_encoder": "post_retrieval.rerank",
}

_IMPORT_NAME_MODULES: dict[str, str] = {
    "faiss": "indexing", "chromadb": "indexing", "qdrant_client": "indexing",
    "pinecone": "indexing", "weaviate": "indexing", "milvus": "indexing",
    "sentence_transformers": "retrieval.embedding", "openai": "retrieval.embedding",
    "rank_bm25": "retrieval", "elasticsearch": "retrieval", "whoosh": "retrieval",
    "cross_encoder": "post_retrieval.rerank", "cohere": "post_retrieval.rerank",
}

_METHOD_NAME_MODULES: dict[str, str] = {
    "rerank": "post_retrieval.rerank",
    "build_context": "post_retrieval.context",
}


@dataclass(frozen=True)
class Finding:
    module: str
    field: str
    value: str
    file: str
    line: int
    pattern: str


@dataclass(frozen=True)
class InspectionResult:
    source_file: str
    findings: list[Finding] = field(default_factory=list)


def _literal_repr(node: ast.expr) -> str:
    try:
        return repr(ast.literal_eval(node))
    except (ValueError, TypeError):
        return ast.unparse(node)


def _scan_dict_literals(tree: ast.Module, source_file: str) -> list[Finding]:
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            module = _DICT_KEY_MODULES.get(key.value)
            if module is None:
                continue
            findings.append(Finding(module=module, field=key.value, value=_literal_repr(value),
                                    file=source_file, line=value.lineno, pattern="dict-literal-key"))
    return findings


def _scan_imports(tree: ast.Module, source_file: str) -> list[Finding]:
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module.split(".")[0]]
        else:
            continue
        line = node.lineno
        for name in names:
            module = _IMPORT_NAME_MODULES.get(name)
            if module is None:
                continue
            findings.append(Finding(module=module, field="import", value=name,
                                    file=source_file, line=line, pattern="import"))
    return findings


def _scan_methods(tree: ast.Module, source_file: str) -> list[Finding]:
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        module = _METHOD_NAME_MODULES.get(node.name)
        if module is None:
            continue
        findings.append(Finding(module=module, field="method_present", value=node.name,
                                file=source_file, line=node.lineno, pattern="method-def"))
    return findings


def inspect_adapter_source(path: str | Path) -> InspectionResult:
    source_path = Path(path)
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    source_file = str(source_path)
    findings = [*_scan_imports(tree, source_file), *_scan_methods(tree, source_file),
                *_scan_dict_literals(tree, source_file)]
    findings.sort(key=lambda item: item.line)
    return InspectionResult(source_file=source_file, findings=findings)


_MODULE_TO_STAGE: dict[str, tuple[str, str]] = {
    "indexing": ("indexing", "chunking"),
    "indexing.chunking": ("indexing", "chunking"),
    "retrieval": ("retrieval", "retriever"),
    "retrieval.embedding": ("retrieval", "embedding"),
    "post_retrieval.rerank": ("post_retrieval", "reranker"),
    "post_retrieval.context": ("post_retrieval", "context"),
    "post_retrieval": ("post_retrieval", "reranker"),
    "generation": ("generation", "generator"),
    "context": ("context", "context"),
}


class NotADraftError(ValueError):
    """Raised when a file passed to `ragnoz architecture approve` is not an inspect draft."""


def draft_to_architecture(draft: dict[str, Any]) -> dict[str, Any]:
    """Convert an inspect draft's findings into the plain `modules:` shape diagnose trusts.

    This is the one explicit approval step: calling it (via `ragnoz architecture approve`)
    is the user deciding these findings are now a trusted declaration, not an automatic
    promotion that happens anywhere else in the pipeline.
    """
    if not draft.get("inspected_draft"):
        raise NotADraftError("Bu dosya bir inspect taslağı değil (inspected_draft: true alanı yok).")
    modules: dict[str, dict[str, dict[str, Any]]] = {}
    for item in draft.get("findings", []):
        stage, subkey = _MODULE_TO_STAGE.get(item["module"], (item["module"], "value"))
        modules.setdefault(stage, {}).setdefault(subkey, {})[item["field"]] = item["value"]
    return {
        "modules": modules,
        "inspected_source": draft.get("source_file"),
        "inspected_utc": draft.get("inspected_utc"),
    }


def inspection_to_draft(result: InspectionResult, inspected_utc: str) -> dict[str, Any]:
    return {
        "inspected_draft": True,
        "source_file": result.source_file,
        "inspected_utc": inspected_utc,
        "findings": [
            {"module": f.module, "field": f.field, "value": f.value, "file": f.file,
             "line": f.line, "pattern": f.pattern}
            for f in result.findings
        ],
        "note": (
            "Bu dosya statik kod taramasının BULGULARIdır (dosya+satır kanıtlı); mimariyi veya "
            "kalitesini ÇIKARMAZ. `ragnoz diagnose` bunu onaylanmadan ölçülmüş girdi saymaz. "
            "Onaylamak için: ragnoz architecture approve <bu dosya> --output architecture.yaml"
        ),
    }
