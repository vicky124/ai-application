"""ClaimChecker implementations: an offline evidence-based checker, an optional LLM judge, and a fallback combinator."""
import json
import re
from dataclasses import dataclass
from typing import Callable

from app.agents import evidence
from app.domain import CONTRADICTED, SUPPORTED, UNCITED, UNSUPPORTED, Claim, ClaimCheck, Source
from app.interfaces import ClaimChecker, Reranker


@dataclass(frozen=True)
class SupportThresholds:
    min_lexical: float = 0.5  # share of the claim's content words found in the cited passages
    min_cross_encoder: float = 0.01  # reranker probability that the cited passage answers the claim
    polarity_min_overlap: float = 0.5  # how well a passage sentence must match the claim to compare yes/no polarity


class SupportScoreChecker:
    """Offline, deterministic checks per claim against the sources it cites:
    1. every number in the claim appears in the cited text,
    2. the closest cited sentence does not say the opposite (negation parity),
    3. enough of the claim's wording is present, and
    4. a cross-encoder (when available) agrees the cited passage states the claim.
    It cannot catch subtle meaning changes without a negation; an LLM judge covers those."""

    def __init__(self, thresholds: SupportThresholds = SupportThresholds(), reranker: Reranker | None = None):
        self._t = thresholds
        self._reranker = reranker

    def check(self, claims: list[Claim], sources: list[Source]) -> list[ClaimCheck]:
        return [self._check_one(c, sources) for c in claims]

    def _check_one(self, claim: Claim, sources: list[Source]) -> ClaimCheck:
        if not claim.cited:
            return ClaimCheck(claim.text, claim.cited, UNCITED, None, "no citation")
        passages = [sources[i - 1] for i in claim.cited if 1 <= i <= len(sources)]
        if not passages:
            return ClaimCheck(claim.text, claim.cited, UNSUPPORTED, None, "cites a source that does not exist")
        texts = [p.text for p in passages]
        joined = "\n".join(texts)

        missing_numbers = sorted(evidence.numbers(claim.text) - evidence.numbers(joined))
        if missing_numbers:
            return ClaimCheck(claim.text, claim.cited, UNSUPPORTED, 0.0, f"number {', '.join(missing_numbers)} is not in the cited source")

        for clause in evidence.clauses(claim.text):
            if len(evidence.content_terms(clause)) < 2:
                continue
            for passage in texts:
                sentence, overlap = evidence.best_sentence(clause, passage)
                if sentence and overlap >= self._t.polarity_min_overlap and evidence.is_negative(clause) != evidence.is_negative(sentence):
                    return ClaimCheck(claim.text, claim.cited, CONTRADICTED, 0.0, f'the source says the opposite: "{sentence}"')

        broader = evidence.unsupported_absolutes(claim.text, joined)
        if broader:
            return ClaimCheck(claim.text, claim.cited, UNSUPPORTED, 0.0, f"goes beyond the source ({', '.join(broader)} is not in it)")

        lexical, missing_words = evidence.clause_coverage(claim.text, joined)
        cross = max(self._reranker.score(claim.text, texts)) if self._reranker else None
        strength = lexical if cross is None else 0.5 * lexical + 0.5 * min(1.0, cross * 2)
        if lexical < self._t.min_lexical:
            return ClaimCheck(claim.text, claim.cited, UNSUPPORTED, strength, f"not stated in the cited source (missing: {', '.join(missing_words[:4])})")
        if cross is not None and cross < self._t.min_cross_encoder:
            return ClaimCheck(claim.text, claim.cited, UNSUPPORTED, strength, "the cited source does not appear to state this")
        return ClaimCheck(claim.text, claim.cited, SUPPORTED, strength, "")


JUDGE_PROMPT = """You check whether claims are supported by source passages.
For each numbered claim you get the passages it cites. Decide:
- "supported": the passages clearly state or directly imply the claim, including its numbers and conditions.
- "contradicted": the passages say something that conflicts with the claim.
- "unsupported": the passages do not state the claim, or the claim says more than they do (extra facts, wider scope).
Use only the passages. Reply with a JSON array and nothing else, one object per claim:
[{"claim": 1, "verdict": "supported" | "unsupported" | "contradicted", "reason": "short reason"}]"""

_JSON_ARRAY = re.compile(r"\[.*\]", re.S)


class JudgeError(RuntimeError):
    """The LLM judge could not produce a usable verdict (provider error or unparsable output)."""


class LLMClaimChecker:
    """Asks a chat model to judge all claims of an answer in a single call. `invoke` takes (system, human) text
    and returns the model's reply as plain text."""

    def __init__(self, invoke: Callable[[str, str], str]):
        self._invoke = invoke

    def check(self, claims: list[Claim], sources: list[Source]) -> list[ClaimCheck]:
        results: dict[int, ClaimCheck] = {}
        todo = []
        for i, c in enumerate(claims, 1):
            passages = [sources[n - 1] for n in c.cited if 1 <= n <= len(sources)]
            if not c.cited:
                results[i] = ClaimCheck(c.text, c.cited, UNCITED, None, "no citation")
            elif not passages:
                results[i] = ClaimCheck(c.text, c.cited, UNSUPPORTED, None, "cites a source that does not exist")
            else:
                todo.append((i, c, passages))
        if todo:
            human = "\n\n".join(
                f"Claim {i}: {c.text}\n" + "\n".join(f"Passage [{n}]: {sources[n - 1].text}" for n in c.cited if 1 <= n <= len(sources))
                for i, c, _ in todo
            )
            try:
                reply = self._invoke(JUDGE_PROMPT, human)
            except Exception as e:  # provider errors are reported without their message (it may contain secrets)
                raise JudgeError(f"judge call failed ({type(e).__name__})") from None
            verdicts = self._parse(reply)
            for i, c, _ in todo:
                v = verdicts.get(i)
                if v is None:
                    raise JudgeError(f"judge did not return a verdict for claim {i}")
                verdict = v["verdict"] if v["verdict"] in (SUPPORTED, UNSUPPORTED, CONTRADICTED) else UNSUPPORTED
                results[i] = ClaimCheck(c.text, c.cited, verdict, 1.0 if verdict == SUPPORTED else 0.0, str(v.get("reason", ""))[:200])
        return [results[i] for i in range(1, len(claims) + 1)]

    @staticmethod
    def _parse(reply: str) -> dict[int, dict]:
        match = _JSON_ARRAY.search(reply)
        if not match:
            raise JudgeError("judge reply contained no JSON array")
        try:
            items = json.loads(match.group(0))
            return {int(x["claim"]): x for x in items}
        except (ValueError, KeyError, TypeError):
            raise JudgeError("judge reply was not valid JSON") from None


class FallbackChecker:
    """Uses `primary`; if it fails (for example the LLM is unreachable) falls back to `secondary` and says so."""

    def __init__(self, primary: ClaimChecker, secondary: ClaimChecker):
        self._primary, self._secondary = primary, secondary
        self.fallbacks = 0  # how often the primary failed, so evaluations can tell judge verdicts from fallback ones

    def check(self, claims: list[Claim], sources: list[Source]) -> list[ClaimCheck]:
        try:
            return self._primary.check(claims, sources)
        except JudgeError:
            self.fallbacks += 1
            return self._secondary.check(claims, sources)
