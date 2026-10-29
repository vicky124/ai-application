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
class Claim:
    """One sentence of an answer that asserts something, with the sources it cites (1-based)."""

    text: str  # the sentence without citation markers
    cited: tuple[int, ...]


# Verdicts a checker can give a claim.
SUPPORTED, UNSUPPORTED, CONTRADICTED, UNCITED = "supported", "unsupported", "contradicted", "uncited"


@dataclass(frozen=True)
class ClaimCheck:
    claim: str
    cited: tuple[int, ...]
    verdict: str  # supported | unsupported | contradicted | uncited
    strength: float | None = None  # 0..1 evidence strength when the checker can express one
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.verdict == SUPPORTED


@dataclass(frozen=True)
class Verification:
    passed: bool
    reason: str = ""
    coverage: float = 0.0
    claims: tuple[ClaimCheck, ...] = ()
    confidence: float | None = None  # heuristic evidence strength 0..1, not a calibrated probability
    hint: str | None = None  # what to fix, fed back to the generator on a retry


@dataclass
class DocumentMeta:
    doc_id: str
    title: str
    department: str = "General"
    version: str = "1.0"
    status: str = "active"
    allowed_roles: list[str] = field(default_factory=lambda: ["all"])
