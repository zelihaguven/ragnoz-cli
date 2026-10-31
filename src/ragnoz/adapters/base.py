from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PipelineAdapter(Protocol):
    """RAGnoz'un opsiyonel uçtan uca pipeline adapter arayüzü.

    Adapter metodları yalnız `ragnoz run --adapter package.module:factory` açıkça
    çağrıldığında çalışır. Dönüş değerleri JSON-uyumlu olmalıdır; `fingerprint(stage)`
    her aşamanın model/ayar/sürüm imzasını ayrı döndürmelidir.
    """

    def load_documents(self) -> list[dict[str, Any]]: ...
    def chunk(self, documents: list[dict[str, Any]]) -> list[dict[str, Any]]: ...
    def index(self, chunks: list[dict[str, Any]]) -> Any: ...
    def retrieve(self, question: str, index: Any) -> list[dict[str, Any]]: ...
    def generate(self, question: str, context: list[dict[str, Any]]) -> str | dict[str, Any]: ...
    def describe(self) -> dict[str, Any]: ...
    def fingerprint(self, stage: str) -> Any: ...


class AdapterError(RuntimeError):
    """Adapter contract or a per-question pipeline stage failed."""
