"""Single-purpose guard and verifier implementations."""
import re

from app.domain import GuardResult, Source, Verification
from app.providers.generators import INSUFFICIENT

_INJECTION = re.compile(
    r"ignore (all |any |the )?(previous|prior|above) (instructions|rules)|reveal (your )?(system )?prompt|"
    r"you are now|disregard .* (rules|instructions)|jailbreak",
    re.I,
)
_CITE = re.compile(r"\[(\d+)\]")
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


class RegexInputGuard:
    def check(self, text: str) -> GuardResult:
        if _INJECTION.search(text):
            return GuardResult(False, "Possible prompt-injection attempt")
        if len(text) > 2000:
            return GuardResult(False, "Question too long")
        return GuardResult(True)


class CitationVerifier:
    """Rule-based groundedness checks: valid citations, sentence coverage, numbers present in sources."""

    def __init__(self, min_coverage: float):
        self._min = min_coverage

    def verify(self, answer: str, sources: list[Source]) -> Verification:
        if answer.strip() == INSUFFICIENT:
            return Verification(True, "model abstained")
        cited = [int(n) for n in _CITE.findall(answer)]
        if not cited:
            return Verification(False, "no citations")
        if any(n < 1 or n > len(sources) for n in cited):
            return Verification(False, "citation refers to a non-existent source")
        sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", answer) if s.strip()]
        coverage = sum(1 for s in sentences if _CITE.search(s)) / max(len(sentences), 1)
        if coverage < self._min:
            return Verification(False, "too many uncited sentences", coverage)
        corpus = " ".join(s.text for s in sources)
        for num in _NUM.findall(_CITE.sub("", answer)):
            if num not in corpus:
                return Verification(False, f"number {num} not found in sources", coverage)
        return Verification(True, "grounded", coverage)
