"""ClaimVerifier: structural rules first, then a claim-by-claim check of what each sentence says against what it cites."""
from app.agents.claims import split_claims
from app.domain import ClaimCheck, Source, Verification
from app.interfaces import ClaimChecker, Verifier
from app.providers.generators import INSUFFICIENT


def _short(text: str, n: int = 90) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def build_hint(bad: list[ClaimCheck]) -> str:
    lines = [f'- "{_short(c.claim)}" (cites {", ".join(f"[{n}]" for n in c.cited) or "nothing"}): {c.reason or c.verdict}' for c in bad[:3]]
    return (
        "Your previous answer contained claims that the cited sources do not support:\n"
        + "\n".join(lines)
        + "\nRewrite the answer using only facts stated in the sources, cite each sentence, "
        f"or reply exactly {INSUFFICIENT} if the sources do not answer the question."
    )


def answer_confidence(checks: list[ClaimCheck]) -> float | None:
    """Evidence strength of the weakest claim (0..1). A heuristic for display, not a calibrated probability."""
    strengths = [c.strength for c in checks if c.strength is not None]
    return min(strengths) if strengths else None


class ClaimVerifier:
    def __init__(self, rules: Verifier, checker: ClaimChecker):
        self._rules = rules
        self._checker = checker

    def verify(self, answer: str, sources: list[Source]) -> Verification:
        base = self._rules.verify(answer, sources)
        if answer.strip() == INSUFFICIENT or not base.passed:
            return base  # an abstention, or a structural problem the rules already explain (with a hint)

        checks = self._checker.check(split_claims(answer), sources)
        confidence = answer_confidence(checks)
        bad = [c for c in checks if not c.ok]
        if bad:
            first = bad[0]
            reason = f'{len(bad)} unsupported claim(s); first: "{_short(first.claim, 60)}" ({first.reason or first.verdict})'
            return Verification(False, reason, base.coverage, tuple(checks), confidence, build_hint(bad))
        return Verification(True, "grounded", base.coverage, tuple(checks), confidence)
