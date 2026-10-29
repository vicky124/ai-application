"""Claim extraction, evidence features, claim checkers, the claim verifier and the agent's retry-with-feedback loop.
Everything here is offline and deterministic; the quality of the checks on realistic answers is measured by
`python -m app.eval.verifier_eval` (see test_verifier_eval.py for the dataset and regression floors)."""
import json

import pytest

from app.agents import evidence
from app.agents.checkers import FallbackChecker, JudgeError, LLMClaimChecker, SupportScoreChecker, SupportThresholds
from app.agents.claims import split_claims
from app.agents.components import CitationVerifier
from app.agents.graph import PolicyAgent
from app.agents.verifier import ClaimVerifier, answer_confidence, build_hint
from app.container import get_container
from app.domain import CONTRADICTED, SUPPORTED, UNCITED, UNSUPPORTED, Claim, ClaimCheck, Source
from app.providers.generators import INSUFFICIENT
from app.rag.rerank import OverlapReranker

ANNUAL = Source("leave-policy", "Leave Policy", "Leave Policy > Annual Leave", None, "2.1",
                "Leave Policy > Annual Leave\nFull-time employees receive 24 days of paid annual leave per calendar year. "
                "Up to 5 unused days may be carried forward to the next year; any remaining days expire on 31 March.", 0.9, 0.9)
SICK = Source("leave-policy", "Leave Policy", "Leave Policy > Sick Leave", None, "2.1",
              "Leave Policy > Sick Leave\nEmployees receive 10 days of paid sick leave per year. A medical certificate is required "
              "for absences longer than 2 consecutive days. Sick leave cannot be carried forward.", 0.8, 0.8)


def checker(**kw):
    return SupportScoreChecker(SupportThresholds(**kw))


def verdicts(answer, sources, **kw):
    return [c.verdict for c in checker(**kw).check(split_claims(answer), sources)]


# ---------------- claim extraction ----------------
def test_split_claims_one_per_sentence_with_citations():
    claims = split_claims("Employees get 24 days of paid leave [1]. Unused days expire on 31 March [1][2].")
    assert [c.cited for c in claims] == [(1,), (1, 2)]
    assert claims[0].text == "Employees get 24 days of paid leave."


def test_citation_placed_after_the_full_stop_stays_with_its_sentence():
    claims = split_claims("Employees get 24 days of paid leave. [1] Sick leave cannot be carried forward. [2]")
    assert [c.cited for c in claims] == [(1,), (2,)]


def test_split_claims_ignores_fragments_and_keeps_uncited_sentences():
    claims = split_claims("Yes. You may carry forward up to 5 days.")
    assert len(claims) == 1 and claims[0].cited == ()
    assert split_claims(INSUFFICIENT) == [Claim(INSUFFICIENT, ())] or split_claims(INSUFFICIENT) == []


# ---------------- evidence features ----------------
def test_stemmer_matches_inflections_but_not_unrelated_words():
    assert evidence.stem("anonymously") == evidence.stem("anonymous")
    assert evidence.stem("preserved") == evidence.stem("preserve")
    assert evidence.stem("days") == evidence.stem("day") and evidence.stem("carried") == evidence.stem("carry")
    assert evidence.stem("business") == "business"  # not a plural


def test_numbers_ignore_formatting():
    assert evidence.numbers("a budget of 1,000 USD and 0.58 per mile, 10:00") == {"1000", "0.58", "10", "00"}


def test_coverage_reports_missing_words():
    cov, missing = evidence.coverage("employees receive a birthday day off", ANNUAL.text)
    assert cov < 0.7 and "birthday" in missing


def test_clauses_split_extra_clauses_but_keep_noun_pairs_together():
    assert evidence.clauses("You get 24 days, plus a birthday day off") == ["You get 24 days", "a birthday day off"]
    assert evidence.clauses("needs approval from HR and Legal") == ["needs approval from HR and Legal"]
    assert len(evidence.clauses("A P1 needs a response within 15 minutes and is escalated to the CEO")) == 2


def test_negation_and_absolute_helpers():
    assert evidence.is_negative("leave cannot be carried forward") and not evidence.is_negative("leave can be carried forward")
    assert evidence.unsupported_absolutes("All unused leave can be carried forward", ANNUAL.text) == ["all"]
    assert evidence.unsupported_absolutes("Any remaining days expire", ANNUAL.text) == []  # the source says 'any'


# ---------------- support checker ----------------
def test_faithful_paraphrase_is_supported():
    assert verdicts("You get 24 days of paid annual leave each calendar year [1].", [ANNUAL]) == [SUPPORTED]


def test_each_fault_type_is_flagged():
    assert verdicts("You get 30 days of paid annual leave per calendar year [1].", [ANNUAL]) == [UNSUPPORTED]  # number
    assert verdicts("Unused sick leave can be carried forward to the next year [1].", [SICK]) == [CONTRADICTED]  # negation
    assert verdicts("You get 24 days of paid annual leave, plus a birthday day off [1].", [ANNUAL]) == [UNSUPPORTED]  # extra clause
    assert verdicts("All unused leave can be carried forward [1].", [ANNUAL]) == [UNSUPPORTED]  # sweeping wording
    assert verdicts("A medical certificate is needed for long absences [1].", [ANNUAL]) == [UNSUPPORTED]  # wrong source
    assert verdicts("You get 24 days of paid annual leave per calendar year.", [ANNUAL]) == [UNCITED]
    assert verdicts("You get 24 days of paid annual leave per calendar year [7].", [ANNUAL]) == [UNSUPPORTED]


def test_two_clause_claim_with_a_negation_is_not_misread_as_a_contradiction():
    assert verdicts("You get 10 days of paid sick leave a year, and it cannot be carried forward [1].", [SICK]) == [SUPPORTED]


def test_reasons_explain_the_verdict():
    reasons = {c.reason for c in checker().check(split_claims("You get 30 days of paid annual leave per calendar year [1]."), [ANNUAL])}
    assert any("number 30" in r for r in reasons)
    contradicted = checker().check(split_claims("Unused sick leave can be carried forward to the next year [1]."), [SICK])[0]
    assert "opposite" in contradicted.reason and "cannot be carried forward" in contradicted.reason


def test_cross_encoder_can_veto_a_claim():
    class Strict:
        def score(self, query, passages):
            return [0.0 for _ in passages]

    c = SupportScoreChecker(SupportThresholds(min_cross_encoder=0.05), Strict())
    out = c.check(split_claims("You get 24 days of paid annual leave per calendar year [1]."), [ANNUAL])
    assert out[0].verdict == UNSUPPORTED and "does not appear to state" in out[0].reason


def test_thresholds_are_respected():
    claim = "Full-time employees receive generous paid annual leave yearly [1]."  # 2 of 9 content words are not in the source
    assert verdicts(claim, [ANNUAL], min_lexical=0.7) == [SUPPORTED]
    assert verdicts(claim, [ANNUAL], min_lexical=0.9) == [UNSUPPORTED]


# ---------------- claim verifier ----------------
def verifier(**kw):
    return ClaimVerifier(CitationVerifier(0.6), SupportScoreChecker(SupportThresholds(**kw), OverlapReranker()))


def test_verifier_passes_grounded_answers_with_confidence_and_claims():
    v = verifier().verify("You get 24 days of paid annual leave each calendar year [1].", [ANNUAL])
    assert v.passed and v.reason == "grounded" and len(v.claims) == 1 and v.claims[0].ok
    assert 0.5 < v.confidence <= 1.0 and v.hint is None


def test_verifier_failure_lists_the_unsupported_claim_and_gives_a_hint():
    v = verifier().verify("You get 24 days of leave [1]. Unused sick leave can be carried forward [2].", [ANNUAL, SICK])
    assert not v.passed and "unsupported" in v.reason
    assert [c.ok for c in v.claims] == [True, False]
    assert "Unused sick leave can be carried forward" in v.hint and "INSUFFICIENT_CONTEXT" in v.hint


def test_rule_failures_pass_through_with_their_own_hint():
    v = verifier().verify("You get 24 days of paid annual leave per calendar year.", [ANNUAL])
    assert not v.passed and v.reason == "no citations" and "Cite" in v.hint and v.claims == ()


def test_abstention_passes_untouched():
    v = verifier().verify(INSUFFICIENT, [ANNUAL])
    assert v.passed and v.claims == ()


def test_confidence_is_the_weakest_claims_strength():
    checks = [ClaimCheck("a", (1,), SUPPORTED, 0.9), ClaimCheck("b", (1,), SUPPORTED, 0.4), ClaimCheck("c", (1,), UNCITED, None)]
    assert answer_confidence(checks) == 0.4 and answer_confidence([]) is None
    assert "Rewrite" in build_hint([ClaimCheck("x y z", (1,), UNSUPPORTED, 0.0, "why")])


# ---------------- LLM judge ----------------
def judge(reply):
    calls = []

    def invoke(system, human):
        calls.append((system, human))
        return reply if not isinstance(reply, Exception) else (_ for _ in ()).throw(reply)

    return LLMClaimChecker(invoke), calls


def test_llm_judge_maps_verdicts_and_sends_claims_with_their_passages():
    reply = 'Sure:\n[{"claim": 1, "verdict": "supported", "reason": "ok"}, {"claim": 2, "verdict": "contradicted", "reason": "says no"}]'
    c, calls = judge(reply)
    out = c.check(split_claims("You get 24 days of paid leave [1]. Unused sick leave can be carried forward [2]."), [ANNUAL, SICK])
    assert [x.verdict for x in out] == [SUPPORTED, CONTRADICTED] and out[1].reason == "says no"
    assert len(calls) == 1  # all claims judged in a single call
    assert "Claim 1:" in calls[0][1] and "Passage [2]:" in calls[0][1] and "cannot be carried forward" in calls[0][1]


def test_llm_judge_does_not_call_the_model_for_uncited_or_missing_sources():
    c, calls = judge("[]")
    out = c.check(split_claims("You get 24 days of paid annual leave per calendar year. You get 24 days of paid leave [9]."), [ANNUAL])
    assert [x.verdict for x in out] == [UNCITED, UNSUPPORTED] and calls == []


def test_llm_judge_unknown_verdict_counts_as_unsupported():
    c, _ = judge('[{"claim": 1, "verdict": "maybe"}]')
    assert c.check(split_claims("You get 24 days of paid leave [1]."), [ANNUAL])[0].verdict == UNSUPPORTED


@pytest.mark.parametrize("reply", ["no json here", "[{broken", '[{"claim": 5, "verdict": "supported"}]'])
def test_llm_judge_bad_replies_raise_judge_error(reply):
    c, _ = judge(reply)
    with pytest.raises(JudgeError):
        c.check(split_claims("You get 24 days of paid leave [1]."), [ANNUAL])


def test_llm_judge_provider_errors_never_leak_their_message():
    c, _ = judge(RuntimeError("quota exceeded for key AIza-SECRET"))
    with pytest.raises(JudgeError) as e:
        c.check(split_claims("You get 24 days of paid leave [1]."), [ANNUAL])
    assert "AIza" not in str(e.value) and "RuntimeError" in str(e.value)


def test_fallback_uses_the_offline_checker_and_counts():
    c, _ = judge(RuntimeError("down"))
    fb = FallbackChecker(c, checker())
    out = fb.check(split_claims("You get 24 days of paid annual leave each calendar year [1]."), [ANNUAL])
    assert out[0].verdict == SUPPORTED and fb.fallbacks == 1


# ---------------- agent: retry with feedback, API output ----------------
class ScriptedGenerator:
    """Returns the scripted answers in order and records the feedback it was given."""

    def __init__(self, *answers):
        self.answers, self.feedback = list(answers), []

    def generate(self, question, sources, feedback=None):
        self.feedback.append(feedback)
        return self.answers.pop(0)


def agent_with(generator, verifier_):
    class OneSource:
        def search(self, query, role, k):
            return [ANNUAL, SICK]

    class Guard:
        def check(self, text):
            from app.domain import GuardResult

            return GuardResult(True)

    return PolicyAgent(Guard(), OneSource(), lambda _id: generator, verifier_, top_k=5, min_score=0.1, max_attempts=2)


def test_agent_retries_with_the_verifiers_feedback_and_then_passes():
    bad = "You get 24 days of paid annual leave, plus a birthday day off [1]."
    good = "You get 24 days of paid annual leave per calendar year [1]."
    gen = ScriptedGenerator(bad, good)
    state = agent_with(gen, verifier()).run("How many leave days?", "employee")
    assert gen.feedback[0] is None and "birthday" in gen.feedback[1]
    assert not state["abstained"] and state["answer"] == good and state["verification"].passed
    assert any("retry with verifier feedback" in t for t in state["trace"])


def test_agent_abstains_when_the_retry_is_still_ungrounded():
    bad = "You get 24 days of paid annual leave, plus a birthday day off [1]."
    state = agent_with(ScriptedGenerator(bad, bad), verifier()).run("How many leave days?", "employee")
    assert state["abstained"] and "could not be verified" in state["abstain_reason"] and "unsupported claim" in state["abstain_reason"]


def test_api_returns_claim_checks_and_confidence(client, alice, monkeypatch):
    from app.config import settings as app_settings

    gen = ScriptedGenerator("Employees receive 10 days of paid sick leave per year [1].")
    monkeypatch.setitem(get_container().models._cache, "extractive", gen)
    r = client.post("/api/chat", headers=alice, json={"question": "How many days of sick leave do I get?", "model_id": "extractive"}).json()
    v = r["verification"]
    assert v["passed"] and v["confidence"] is not None
    assert v["claims"] and v["claims"][0]["verdict"] == "supported" and v["claims"][0]["cited"] == [1]
    assert app_settings.verifier_mode == "claims"


def test_api_retry_trace_when_first_answer_is_unsupported(client, alice, monkeypatch):
    gen = ScriptedGenerator(
        "Employees receive 10 days of paid sick leave per year, plus a free gym membership [1].",
        "Employees receive 10 days of paid sick leave per year [1].",
    )
    monkeypatch.setitem(get_container().models._cache, "extractive", gen)
    r = client.post("/api/chat", headers=alice, json={"question": "How many days of sick leave do I get?", "model_id": "extractive"}).json()
    assert not r["abstained"] and any("retry with verifier feedback" in t for t in r["trace"])
    assert gen.feedback[0] is None and "gym" in gen.feedback[1]


# ---------------- container wiring ----------------
@pytest.mark.parametrize("mode,expected", [("rules", CitationVerifier), ("claims", ClaimVerifier), ("llm", ClaimVerifier)])
def test_container_selects_the_verifier_by_mode(tmp_path, mode, expected):
    from app.config import Settings
    from app.container import Container

    c = Container(Settings(_env_file=None, qdrant_url=None, qdrant_path=str(tmp_path), embedding_provider="hash", reranker_provider="none", verifier_mode=mode, autoload_samples=False))
    assert isinstance(c.verifier, expected)
    c.store.close()


def test_container_rejects_an_unknown_verifier_mode(tmp_path):
    from app.config import Settings
    from app.container import Container

    with pytest.raises(ValueError, match="VERIFIER_MODE"):
        Container(Settings(_env_file=None, qdrant_url=None, qdrant_path=str(tmp_path), embedding_provider="hash", reranker_provider="none", verifier_mode="magic", autoload_samples=False))


def test_llm_mode_falls_back_offline_when_the_judge_model_is_unavailable(tmp_path):
    from app.config import Settings
    from app.container import Container

    c = Container(Settings(_env_file=None, qdrant_url=None, qdrant_path=str(tmp_path), embedding_provider="hash", reranker_provider="none", verifier_mode="llm", google_api_key=None, autoload_samples=False))
    v = c.verifier.verify("You get 24 days of paid annual leave each calendar year [1].", [ANNUAL])  # no Gemini key: judge unavailable
    assert v.passed and v.claims  # answered by the offline checker instead
    c.store.close()
