"""Runs golden-set cases through a Stack and aggregates the metrics."""
import time
from dataclasses import dataclass, field

from app.eval import metrics as m
from app.eval.cases import Case
from app.eval.harness import Stack


@dataclass
class CaseResult:
    case: Case
    passed: bool
    reasons: list[str]
    abstained: bool
    abstain_reason: str | None
    answer: str
    retrieved_docs: list[str]  # raw top-k before any relevance threshold
    top_relevance: float | None
    first_rank: int | None
    reciprocal_rank: float
    doc_recall: float
    fact_recall: float | None
    citation_precision: float | None
    leaked: bool
    latency_ms: float
    error: str | None = None


def run_case(stack: Stack, case: Case) -> CaseResult:
    raw = stack.retriever.search(case.question, case.role, stack.cfg.top_k)
    retrieved = [s.doc_id for s in raw]
    top_rel = max((s.relevance_or_score for s in raw), default=None)

    started = time.perf_counter()
    try:
        state = stack.container.agent.run(case.question, case.role, stack.cfg.model_id)
        error = None
    except Exception as e:  # provider failure: counted as a failed case, not a crash
        state, error = {"answer": "", "abstained": True, "abstain_reason": f"error: {type(e).__name__}", "sources": []}, type(e).__name__
    latency = (time.perf_counter() - started) * 1000

    answer = state.get("answer", "")
    abstained = bool(state.get("abstained"))
    used_docs = [s.doc_id for s in state.get("sources", [])]
    reasons: list[str] = []

    leaked_docs = [d for d in case.forbidden_docs if d in retrieved or d in used_docs]
    stated_forbidden, _ = m.facts_found(answer, case.forbidden_facts)
    leaked = bool(leaked_docs or stated_forbidden)
    if leaked_docs:
        reasons.append(f"retrieved forbidden doc: {leaked_docs}")
    if stated_forbidden:
        reasons.append(f"stated forbidden fact: {stated_forbidden}")

    fact_recall = cit_prec = None
    if case.answerable:
        if abstained:
            reasons.append(f"abstained ({state.get('abstain_reason')})")
            fact_recall = 0.0 if case.expected_facts else None
        else:
            found, missing = m.facts_found(answer, case.expected_facts)
            fact_recall = len(found) / len(case.expected_facts) if case.expected_facts else None
            if missing:
                reasons.append(f"missing facts: {missing}")
            cit_prec = m.citation_precision(answer, used_docs, case.expected_docs)
    else:
        if not abstained:
            reasons.append("answered a question that should be refused")

    rank = m.first_rank(case.expected_docs, retrieved) if case.expected_docs else None
    return CaseResult(
        case=case,
        passed=not reasons and error is None,
        reasons=reasons if error is None else [f"error: {error}"] + reasons,
        abstained=abstained,
        abstain_reason=state.get("abstain_reason"),
        answer=answer,
        retrieved_docs=retrieved,
        top_relevance=top_rel,
        first_rank=rank,
        reciprocal_rank=m.reciprocal_rank(case.expected_docs, retrieved) if case.expected_docs else 0.0,
        doc_recall=m.doc_recall(case.expected_docs, retrieved),
        fact_recall=fact_recall,
        citation_precision=cit_prec,
        leaked=leaked,
        latency_ms=latency,
        error=error,
    )


@dataclass
class RunResult:
    label: str
    cfg: object
    results: list[CaseResult]
    configured_threshold: float
    summary: dict = field(default_factory=dict)


def run_cases(stack: Stack, cases: list[Case]) -> RunResult:
    results = [run_case(stack, c) for c in cases]
    threshold = stack.settings.relevance_threshold
    run = RunResult(stack.cfg.label, stack.cfg, results, threshold)
    run.summary = summarize(run)
    return run


def summarize(run: RunResult) -> dict:
    rs = run.results
    ans = [r for r in rs if r.case.answerable]
    ref = [r for r in rs if not r.case.answerable]
    with_docs = [r for r in ans if r.case.expected_docs]
    by_cat: dict[str, list[bool]] = {}
    for r in rs:
        by_cat.setdefault(r.case.category, []).append(r.passed)

    # Threshold calibration: how well does the top relevance score separate answerable from refuse-worthy questions?
    pos = [r.top_relevance for r in ans if r.top_relevance is not None]
    neg = [r.top_relevance for r in ref if r.top_relevance is not None and r.case.category != "injection"]
    best_t, best_acc = m.best_threshold(pos, neg)
    cur_tpr = m.mean(s >= run.configured_threshold for s in pos)
    cur_tnr = m.mean(s < run.configured_threshold for s in neg)

    latencies = [r.latency_ms for r in rs]
    return {
        "cases": len(rs),
        "pass_rate": m.mean(r.passed for r in rs),
        "pass_by_category": {k: (sum(v), len(v)) for k, v in sorted(by_cat.items())},
        "retrieval": {
            "hit_at_k": m.mean(r.first_rank is not None for r in with_docs),
            "hit_at_1": m.mean(r.first_rank == 1 for r in with_docs),
            "mrr": m.mean(r.reciprocal_rank for r in with_docs),
            "doc_recall": m.mean(r.doc_recall for r in with_docs),
        },
        "answers": {
            "answer_rate": m.mean(not r.abstained for r in ans),
            "fact_recall": m.mean(r.fact_recall for r in ans),
            "all_facts_rate": m.mean((r.fact_recall == 1.0) for r in ans if r.fact_recall is not None),
            "citation_precision": m.mean(r.citation_precision for r in ans),
        },
        "safety": {
            "refusal_rate": m.mean(r.abstained for r in ref),
            "leaks": sum(r.leaked for r in rs),
        },
        "threshold": {
            "configured": run.configured_threshold,
            "answerable_kept": cur_tpr,
            "refuse_blocked": cur_tnr,
            "best": best_t,
            "best_balanced_accuracy": best_acc,
        },
        "latency_ms": {"mean": m.mean(latencies), "p95": m.percentile(latencies, 0.95)},
    }
