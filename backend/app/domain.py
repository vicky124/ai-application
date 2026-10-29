"""Plain domain types shared across layers (no framework dependencies)."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedPage:
    text: str
    page: int | None = None


@dataclass(frozen=True)
class Source:
    """A retrieved chunk presented to the generator and returned as a citation."""

    doc_id: str
    title: str
    section: str
    page: int | None
    version: str
    text: str
    score: float  # the score the retriever ranked by (cosine, fused rank score or reranker probability)
    # Calibrated 0..1 estimate of how relevant the passage is to the question. The agent abstains below a threshold on
    # this, so it must be comparable across questions (unlike a rank-fusion score). None means "use score".
    relevance: float | None = None

    @property
    def relevance_or_score(self) -> float:
        return self.score if self.relevance is None else self.relevance


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str = ""


@dataclass(frozen=True)
class Verification:
    passed: bool
    reason: str = ""
    coverage: float = 0.0


@dataclass
class DocumentMeta:
    doc_id: str
    title: str
    department: str = "General"
    version: str = "1.0"
    status: str = "active"
    allowed_roles: list[str] = field(default_factory=lambda: ["all"])
