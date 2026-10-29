"""The labeled verifier datasets: integrity checks, and regression floors for the offline claim verifier.

The floors on the held-out set guard against silent regressions; they are deliberately far below the dev-set score
because the dev set was used to shape the heuristics (see docs/phase2-verifier-evaluation.md). Do not tune on the
held-out set: add new cases to it instead."""
import pytest

from app.agents.checkers import SupportThresholds
from app.agents.components import CitationVerifier
from app.config import Settings
from app.eval import verifier_eval as ve

SETTINGS = Settings(_env_file=None)


@pytest.fixture(scope="module")
def chunks():
    return ve.corpus_chunks()


@pytest.fixture(scope="module")
def dev():
    return ve.load_cases(ve.CASES_PATH)


@pytest.fixture(scope="module")
def holdout():
    return ve.load_cases(ve.HOLDOUT_PATH)


def test_every_case_resolves_its_sources_from_the_corpus(dev, holdout, chunks):
    for case in dev + holdout:
        assert ve.sources_for(case, chunks), case.id


def test_ids_are_unique_across_both_sets_and_splits_are_what_they_claim(dev, holdout):
    ids = [c.id for c in dev + holdout]
    assert len(ids) == len(set(ids))
    assert {c.split for c in dev} == {"dev", "test"} and {c.split for c in holdout} == {"holdout"}
    assert abs(sum(c.split == "dev" for c in dev) - sum(c.split == "test" for c in dev)) <= 1


def test_labels_are_consistent(dev, holdout):
    for case in dev + holdout:
        assert case.supported == (case.fault == "faithful"), case.id
        assert "[" in case.answer or case.fault in ("no_citation",), case.id
    for cases in (dev, holdout):
        assert sum(c.supported for c in cases) >= 20 and sum(not c.supported for c in cases) >= 20


def test_faithful_answers_are_well_formed_so_a_pass_depends_only_on_content(dev, holdout, chunks):
    rules = CitationVerifier(SETTINGS.min_citation_coverage)
    for case in dev + holdout:
        if case.supported:
            assert rules.verify(case.answer, ve.sources_for(case, chunks)).passed, case.id


def test_holdout_covers_the_subtle_fault_types_the_offline_checks_cannot_catch(holdout):
    faults = {c.fault for c in holdout if not c.supported}
    assert {"role_swap", "flipped_condition", "unit_change", "number_swap", "entity_swap"} <= faults


def test_confusion_metrics_on_known_results():
    from app.domain import Verification

    def case(i, supported):
        return ve.VerifierCase(f"c{i}", "faithful" if supported else "x", supported, "a [1]", (), "dev")

    results = [
        (case(1, True), Verification(True)),  # correct pass
        (case(2, True), Verification(False)),  # false alarm
        (case(3, False), Verification(False)),  # caught
        (case(4, False), Verification(True)),  # missed
    ]
    m = ve.confusion(results)
    assert m["recall"] == 0.5 and m["false_alarm_rate"] == 0.5 and m["precision"] == 0.5 and m["accuracy"] == 0.5
    assert ve.per_fault_recall(results) == {"x": (1, 2)}


def run(cases, chunks, name="lexical"):
    verifier = ve.build_verifier(name, SupportThresholds(), SETTINGS)
    return ve.confusion(ve.run_verifier(verifier, cases, chunks))


def test_regression_floor_on_the_dev_set(dev, chunks):
    m = run(dev, chunks)
    assert m["recall"] >= 0.9 and m["false_alarm_rate"] <= 0.1


def test_regression_floor_on_the_held_out_set(holdout, chunks):
    m = run(holdout, chunks)
    assert m["recall"] >= 0.35, "the offline checks caught 40% of held-out faulty answers when measured"
    assert m["false_alarm_rate"] <= 0.15, "10% of faithful held-out answers were flagged when measured"


def test_claim_checks_beat_rules_only_on_both_sets(dev, holdout, chunks):
    for cases in (dev, holdout):
        assert run(cases, chunks)["recall"] > run(cases, chunks, "rules")["recall"] + 0.25


def test_threshold_calibration_returns_thresholds_and_a_leaderboard(dev, chunks):
    from app.rag.rerank import OverlapReranker

    thresholds, top = ve.calibrate(dev, chunks, SETTINGS, ve.CachedReranker(OverlapReranker()))
    assert 0.3 <= thresholds.min_lexical <= 0.8 and 0 < thresholds.min_cross_encoder < 1
    assert len(top) == 5 and top[0][2]["balanced_accuracy"] >= top[-1][2]["balanced_accuracy"]
