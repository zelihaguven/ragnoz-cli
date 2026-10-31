from __future__ import annotations

from enum import IntEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ExpectedBehavior = Literal["answer", "abstain", "clarify"]
QuestionType = Literal[
    "factual", "numeric", "unanswerable", "multi_hop", "ambiguous", "procedural", "exact_id"
]


class Observability(IntEnum):
    L0 = 0  # answer only
    L1 = 1  # answer plus final sources/context
    L2 = 2  # candidate and post-rerank lists
    L3 = 3  # chunking/ingestion is observable

    @classmethod
    def parse(cls, value: str | int | Observability) -> Observability:
        if isinstance(value, cls):
            return value
        if isinstance(value, int):
            return cls(value)
        return cls[value.upper()]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="allow")
    doc_id: str
    page: str | int | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote: str | None = None


class GoldenItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    question: str
    lang: str = "en"
    type: QuestionType = "factual"
    tags: list[str] = Field(default_factory=list)
    expected_behavior: ExpectedBehavior = "answer"
    expected_answer: str | None = None
    expected_values: list[dict[str, Any] | float | int | str] = Field(default_factory=list)
    expected_values_mode: Literal["any", "all"] = "any"
    numeric_tolerance: float = Field(default=0.0, ge=0)
    expected_min: float | None = None
    expected_max: float | None = None
    unit: str | None = None
    must_include: list[str] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    evidence_mode: Literal["any", "all"] = "any"
    forbid_docs: list[str] = Field(default_factory=list)
    clarify_options: list[str] = Field(default_factory=list)
    provenance: str | dict[str, Any] | None = None

    @field_validator("id", "question")
    @classmethod
    def non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class ScoredChunk(BaseModel):
    model_config = ConfigDict(extra="allow")
    chunk_id: str | None = None
    doc_id: str
    page: str | int | None = None
    text: str = ""
    score: float | None = None
    rank: int | None = None
    char_start: int | None = None
    char_end: int | None = None


class TraceAnswer(BaseModel):
    model_config = ConfigDict(extra="allow")
    text: str = ""
    abstained: bool = False
    clarify_options: list[str] = Field(default_factory=list)
    cited_chunk_ids: list[str] = Field(default_factory=list)


class QuestionTrace(BaseModel):
    model_config = ConfigDict(extra="allow")
    question_id: str
    question: str | None = None
    answer: TraceAnswer | None = None
    route: Literal["answered", "abstained", "clarified", "error"] = "answered"
    candidates: list[ScoredChunk] = Field(default_factory=list)
    ranked: list[ScoredChunk] = Field(default_factory=list)
    context: list[ScoredChunk] = Field(default_factory=list)
    latency_ms: float | None = None
    error: str | None = None
    observability: Literal["L0", "L1", "L2", "L3"] | None = None
    query_variants: list[str] = Field(default_factory=list)
    retrieval_rounds: int | None = None
    route_label: str | None = None
    memory_used: bool | None = None
    seed: int | None = None
    synthetic_fixture: bool = False

    @field_validator("answer", mode="before")
    @classmethod
    def coerce_answer(cls, value: Any) -> Any:
        if value is None or isinstance(value, (TraceAnswer, dict)):
            return value
        return {"text": str(value)}

    @field_validator("observability", mode="before")
    @classmethod
    def infer_observability(cls, value: Any, info: Any) -> Any:
        if value:
            return value
        data = info.data
        if "candidates" in data and "ranked" in data and "context" in data:
            return "L2"
        if "context" in data:
            return "L1"
        return "L0"


class ItemEvaluation(BaseModel):
    question_id: str
    correct: bool | None = None
    evidence_in_candidates: bool | None = None
    evidence_in_ranked: bool | None = None
    evidence_in_context: bool | None = None
    answer: str = ""
    reason: str = ""
    attribution: str = "UNDETERMINED_L0"
    secondary: list[str] = Field(default_factory=list)
    latency_ms: float | None = None


class EvidenceRef(BaseModel):
    metric: str
    value: float
    ci95: tuple[float, float] | None = None
    n: int
    item_ids: list[str]


class Recommendation(BaseModel):
    id: str
    rule_id: str
    rule_version: str = "1.0.0"
    target_module: str
    findings: list[EvidenceRef] = Field(min_length=1)
    hypothesis: str
    change: str
    alternatives: list[str] = Field(default_factory=list)
    expected_impact: dict[str, Any]
    confidence: Literal["low", "medium", "high"]
    confidence_reasons: list[str]
    cost_risk: list[str] = Field(default_factory=list)
    experiment: dict[str, Any]
    status: Literal[
        "proposed", "experiment_run", "verified", "refuted", "inconclusive", "accepted", "rejected"
    ] = "proposed"
    cannot_infer: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    id: str
    title: str
    module: str
    severity: Literal["info", "warning", "critical"]
    measured: str
    threshold: str
    item_ids: list[str] = Field(default_factory=list)
    observability: str
    confidence: Literal["low", "medium", "high"]
    source: str = "trace"
    rule_version: str = "1.0.0"
    explanation: str


class ArchitectureProfile(BaseModel):
    system: str = "unknown"
    paradigm: Literal["Naive", "Advanced", "Modular", "Undetermined"] = "Undetermined"
    flow: Literal["linear", "conditional", "branching", "loop", "unknown"] = "unknown"
    observability: Literal["L0", "L1", "L2", "L3"] = "L0"
    modules: dict[str, Any] = Field(default_factory=dict)
    facts: list[dict[str, Any]] = Field(default_factory=list)
    mismatches: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    taxonomy_note: str = "Paradigma etiketleri betimleyicidir; kalite sıralaması değildir."


class Guidance(BaseModel):
    """Ölçülmemiş yönlendirme: NEREYE bakılacağını söyler, NE YAPILACAĞINI söylemez.

    Kasıtlı olarak `change`/`hypothesis`/`confidence`/`experiment` alanları yok; extra="forbid"
    bu alanların sonradan sızmasını tip seviyesinde engeller. Gerçek, ölçülmüş düzeltme önerisi
    için bkz. Recommendation (ragnoz diagnose çıktısı).
    """

    model_config = ConfigDict(extra="forbid")
    symptom: str
    module: str
    rule_ids: list[str] = Field(default_factory=list)
    next_command: str
    note: str = "Bu bir yönlendirmedir; ölçülmüş bulgu değildir ve bir düzeltme önermez."
