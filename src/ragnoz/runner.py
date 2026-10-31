from __future__ import annotations

import inspect
from typing import Any

from ragnoz.adapters.base import AdapterError
from ragnoz.cache import StageCache, canonical_hash
from ragnoz.schemas import GoldenItem, QuestionTrace

STAGES = ("chunk", "index", "retrieve", "rerank", "context", "generate")


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


class PipelineRunner:
    """Run a synchronous adapter with independently invalidated stage caches."""

    def __init__(self, adapter: Any, cache: StageCache | None = None, no_cache: bool = False) -> None:
        self.adapter = adapter
        self.cache = cache or StageCache()
        self.no_cache = no_cache
        self.cacheable_calls = 0

    def _fingerprint(self, stage: str) -> Any:
        method = getattr(self.adapter, "fingerprint", None)
        if callable(method):
            return method(stage)
        fn = getattr(self.adapter, stage, None)
        try:
            source = inspect.getsource(fn) if fn else "identity"
        except (OSError, TypeError):
            source = getattr(fn, "__qualname__", "identity")
        return {"adapter": f"{type(self.adapter).__module__}.{type(self.adapter).__qualname__}",
                "stage": stage, "method_source_sha256": canonical_hash(source),
                "config": _jsonable(getattr(self.adapter, "config", {}))}

    def _stage(self, stage: str, input_value: Any, operation: Any) -> Any:
        key = self.cache.key(stage, input_value, self._fingerprint(stage))
        if not self.no_cache:
            cached = self.cache.get(key)
            if cached is not None:
                return cached
        self.cacheable_calls += 1
        try:
            result = _jsonable(operation())
            # Validate serializability before caching so failures are attributed to the stage.
            canonical_hash(result)
        except Exception as exc:
            raise AdapterError(f"Aşama {stage!r} başarısız ({type(exc).__name__}); ham hata metni gizlilik için atlandı.") from exc
        if not self.no_cache:
            self.cache.put(key, result)
        return result

    def run(self, items: list[GoldenItem]) -> list[QuestionTrace]:
        try:
            documents = _jsonable(self.adapter.load_documents())
            chunks = self._stage("chunk", documents, lambda: self.adapter.chunk(documents))
            index = self._stage("index", chunks, lambda: self.adapter.index(chunks))
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(f"Doküman yükleme aşaması başarısız ({type(exc).__name__}); ham hata metni gizlilik için atlandı.") from exc

        traces: list[QuestionTrace] = []
        for item in items:
            try:
                query = item.question
                candidates = self._stage("retrieve", {"query": query, "index": index},
                                         lambda query=query, index=index: self.adapter.retrieve(query, index))
                reranker = getattr(self.adapter, "rerank", None)
                ranked = self._stage("rerank", {"query": query, "candidates": candidates},
                                     lambda query=query, candidates=candidates, reranker=reranker: reranker(query, candidates) if callable(reranker) else candidates)
                context_builder = getattr(self.adapter, "build_context", None)
                context = self._stage("context", {"query": query, "ranked": ranked},
                                      lambda query=query, ranked=ranked, context_builder=context_builder: context_builder(query, ranked) if callable(context_builder) else ranked)
                answer = self._stage("generate", {"query": query, "context": context},
                                     lambda query=query, context=context: self.adapter.generate(query, context))
                trace = QuestionTrace.model_validate({
                    "question_id": item.id, "question": query, "answer": answer,
                    "route": "answered", "candidates": candidates, "ranked": ranked,
                    "context": context, "observability": "L3",
                })
                traces.append(trace)
            except Exception as exc:  # noqa: BLE001 - preserve an item-level SYS_ERROR and continue the run
                traces.append(QuestionTrace(
                    question_id=item.id, question=item.question, route="error",
                    error=f"Adapter aşaması başarısız ({type(exc).__name__}); ham hata metni gizlilik için atlandı.", observability="L3",
                ))
        return traces
