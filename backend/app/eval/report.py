"""Plain-text and JSON reporting for evaluation runs."""
from app.eval.runner import RunResult


def pct(x: float | None) -> str:
    return "  n/a" if x is None else f"{x * 100:5.1f}%"


def num(x: float | None, digits: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def thr(x: float | None) -> str:
    """Thresholds can be tiny for cross-encoder probabilities, so show more digits when needed."""
    return "n/a" if x is None else (f"{x:.2f}" if x >= 0.01 else f"{x:.4f}")


def render_run(run: RunResult, show_failures: bool = True) -> str:
    s = run.summary
    lines = [f"=== {run.label}  (model: {run.cfg.model_id}, embeddings: {run.cfg.embedding_provider}, top_k: {run.cfg.top_k}) ==="]
    lines.append(f"cases: {s['cases']}   overall pass rate: {pct(s['pass_rate'])}")
    lines.append("")
    lines.append("by category (passed/total):")
    for cat, (ok, total) in s["pass_by_category"].items():
        lines.append(f"  {cat:<14} {ok:>2}/{total:<2}  {pct(ok / total)}")
    r, a, sf, t, lat = s["retrieval"], s["answers"], s["safety"], s["threshold"], s["latency_ms"]
    lines += [
        "",
        f"retrieval   hit@k {pct(r['hit_at_k'])}   hit@1 {pct(r['hit_at_1'])}   MRR {num(r['mrr'])}   doc recall {pct(r['doc_recall'])}",
        f"answers     answered {pct(a['answer_rate'])}   all facts {pct(a['all_facts_rate'])}   fact recall {pct(a['fact_recall'])}   citation precision {pct(a['citation_precision'])}",
        f"safety      refused when it should {pct(sf['refusal_rate'])}   leaks {sf['leaks']}",
        f"threshold   configured {thr(t['configured'])}: keeps {pct(t['answerable_kept'])} of answerable, blocks {pct(t['refuse_blocked'])} of refusals;"
        f" best {thr(t['best'])} would reach balanced accuracy {pct(t['best_balanced_accuracy'])}",
        f"latency     mean {num(lat['mean'], 0)} ms   p95 {num(lat['p95'], 0)} ms (agent run, excludes the separate retrieval probe)",
    ]
    failed = [x for x in run.results if not x.passed]
    if show_failures and failed:
        lines += ["", f"failures ({len(failed)}):"]
        for x in failed:
            lines.append(f"  - {x.case.id} [{x.case.category}] {x.case.question}")
            lines.append(f"      {'; '.join(x.reasons)}")
            if x.case.expected_docs:
                lines.append(f"      expected {list(x.case.expected_docs)}, retrieved {x.retrieved_docs}")
    return "\n".join(lines)


def render_comparison(runs: list[RunResult]) -> str:
    rows = [
        ("overall pass rate", lambda s: pct(s["pass_rate"])),
        ("retrieval hit@k", lambda s: pct(s["retrieval"]["hit_at_k"])),
        ("retrieval hit@1", lambda s: pct(s["retrieval"]["hit_at_1"])),
        ("retrieval MRR", lambda s: num(s["retrieval"]["mrr"])),
        ("doc recall", lambda s: pct(s["retrieval"]["doc_recall"])),
        ("answered (answerable)", lambda s: pct(s["answers"]["answer_rate"])),
        ("all facts correct", lambda s: pct(s["answers"]["all_facts_rate"])),
        ("citation precision", lambda s: pct(s["answers"]["citation_precision"])),
        ("refused when should", lambda s: pct(s["safety"]["refusal_rate"])),
        ("leaks", lambda s: str(s["safety"]["leaks"])),
        ("threshold (configured)", lambda s: thr(s["threshold"]["configured"])),
        ("best threshold", lambda s: thr(s["threshold"]["best"])),
        ("balanced acc @ best", lambda s: pct(s["threshold"]["best_balanced_accuracy"])),
        ("latency mean ms", lambda s: num(s["latency_ms"]["mean"], 0)),
    ]
    width = max(len(r.label) for r in runs) + 2
    head = f"{'metric':<24}" + "".join(f"{r.label:>{max(width, 12)}}" for r in runs)
    out = [head, "-" * len(head)]
    for name, fn in rows:
        out.append(f"{name:<24}" + "".join(f"{fn(r.summary):>{max(width, 12)}}" for r in runs))
    return "\n".join(out)


def to_dict(run: RunResult) -> dict:
    return {
        "label": run.label,
        "config": {k: getattr(run.cfg, k) for k in run.cfg.__dataclass_fields__},
        "summary": run.summary,
        "cases": [
            {
                "id": x.case.id,
                "category": x.case.category,
                "role": x.case.role,
                "passed": x.passed,
                "reasons": x.reasons,
                "abstained": x.abstained,
                "abstain_reason": x.abstain_reason,
                "retrieved_docs": x.retrieved_docs,
                "first_rank": x.first_rank,
                "top_relevance": x.top_relevance,
                "fact_recall": x.fact_recall,
                "citation_precision": x.citation_precision,
                "latency_ms": round(x.latency_ms, 1),
            }
            for x in run.results
        ],
    }
