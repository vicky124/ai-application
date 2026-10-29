"""Measures the groundedness verifier on labeled answers (eval/verifier_cases.json).

    python -m app.eval.verifier_eval --verifiers rules,lexical,claims          compare verifiers
    python -m app.eval.verifier_eval --verifiers claims --calibrate             pick thresholds on the dev split only
    python -m app.eval.verifier_eval --verifiers llm --llm gemini-3.5-flash-lite --limit 8   small live LLM-judge check

Positive class = "the answer has an unsupported claim". Reported: recall on faulty answers (how many bad answers are
caught), false-alarm rate on faithful answers, precision, accuracy, and recall per fault type. Cases alternate between a
dev split (used to calibrate thresholds) and a held-out test split.
"""
import argparse
import json
import sys
from dataclasses import dataclass
from itertools import product

from app.agents.checkers import FallbackChecker, LLMClaimChecker, SupportScoreChecker, SupportThresholds
from app.agents.components import CitationVerifier
from app.agents.verifier import ClaimVerifier
from app.config import BASE_DIR, Settings
from app.domain import Source, Verification
from app.eval.cases import CORPUS_DIRS, EVAL_DIR
from app.eval.metrics import mean
from app.interfaces import Reranker, Verifier
from app.rag.chunking import chunk_text
from app.rag.text import clean_text, parse_frontmatter

CASES_PATH = EVAL_DIR / "verifier_cases.json"
FALLBACK_CHECKERS: list[FallbackChecker] = []  # judges built by build_verifier, inspected for fallbacks after a run


@dataclass(frozen=True)
class VerifierCase:
    id: str
    fault: str
    supported: bool
    answer: str
    sources: tuple[tuple[str, str], ...]  # (document id, section name)
    split: str  # dev | test


HOLDOUT_PATH = EVAL_DIR / "verifier_holdout.json"


def load_cases(path=CASES_PATH) -> list[VerifierCase]:
    """The development set alternates dev/test by position; a file marked "holdout": true is entirely 'holdout'."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        VerifierCase(
            c["id"], c["fault"], c["supported"], c["answer"], tuple((s["doc"], s["section"]) for s in c["sources"]),
            "holdout" if data.get("holdout") else ("dev" if i % 2 == 0 else "test"),
        )
        for i, c in enumerate(data["cases"])
    ]


def corpus_chunks() -> dict[tuple[str, str], Source]:
    """{(doc_id, section): Source} for every chunk of the evaluation corpus, built without any index or embeddings."""
    chunks: dict[tuple[str, str], Source] = {}
    for directory in CORPUS_DIRS:
        for path in sorted(directory.glob("*.md")):
            meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            doc_id = meta.get("doc_id", path.stem)
            for ch in chunk_text(clean_text(body), 900, 150):
                section = ch.section.split(" > ")[-1]
                chunks[(doc_id, section)] = Source(doc_id, meta.get("title", doc_id), ch.section, None, meta.get("version", ""), ch.text, 1.0, 1.0)
    return chunks


def sources_for(case: VerifierCase, chunks: dict) -> list[Source]:
    missing = [k for k in case.sources if k not in chunks]
    if missing:
        raise KeyError(f"{case.id}: unknown corpus section(s) {missing}")
    return [chunks[k] for k in case.sources]


class CachedReranker:
    """Memoizes a reranker so a threshold grid search does not re-score the same (claim, passage) pairs."""

    def __init__(self, inner: Reranker):
        self._inner, self._cache = inner, {}

    def score(self, query: str, passages: list[str]) -> list[float]:
        key = (query, tuple(passages))
        if key not in self._cache:
            self._cache[key] = self._inner.score(query, passages)
        return self._cache[key]


# ---------------- metrics ----------------
def confusion(results: list[tuple[VerifierCase, Verification]]) -> dict:
    faulty = [(c, v) for c, v in results if not c.supported]
    faithful = [(c, v) for c, v in results if c.supported]
    caught = sum(1 for _, v in faulty if not v.passed)
    false_alarms = sum(1 for _, v in faithful if not v.passed)
    flagged = caught + false_alarms
    tp, fp, fn = caught, false_alarms, len(faulty) - caught
    return {
        "n": len(results),
        "recall": caught / len(faulty) if faulty else None,
        "false_alarm_rate": false_alarms / len(faithful) if faithful else None,
        "precision": tp / flagged if flagged else None,
        "accuracy": (caught + len(faithful) - false_alarms) / len(results) if results else None,
        "f1": (2 * tp / (2 * tp + fp + fn)) if (2 * tp + fp + fn) else None,
        "balanced_accuracy": ((caught / len(faulty)) + (1 - false_alarms / len(faithful))) / 2 if faulty and faithful else None,
        "faulty": len(faulty),
        "faithful": len(faithful),
    }


def per_fault_recall(results) -> dict[str, tuple[int, int]]:
    out: dict[str, list[bool]] = {}
    for c, v in results:
        if not c.supported:
            out.setdefault(c.fault, []).append(not v.passed)
    return {k: (sum(v), len(v)) for k, v in sorted(out.items())}


def run_verifier(verifier: Verifier, cases: list[VerifierCase], chunks: dict) -> list[tuple[VerifierCase, Verification]]:
    return [(c, verifier.verify(c.answer, sources_for(c, chunks))) for c in cases]


# ---------------- construction ----------------
def build_verifier(name: str, thresholds: SupportThresholds, settings: Settings, llm_model: str | None = None, reranker: Reranker | None = None) -> Verifier:
    rules = CitationVerifier(settings.min_citation_coverage)
    if name == "rules":
        return rules
    if name == "lexical":
        return ClaimVerifier(rules, SupportScoreChecker(thresholds))
    if name == "claims":
        return ClaimVerifier(rules, SupportScoreChecker(thresholds, reranker))
    if name == "llm":
        from app.providers.generators import ModelCatalog

        generator = ModelCatalog(settings.models, settings).get(llm_model)
        if not hasattr(generator, "complete"):
            raise SystemExit(f"model '{llm_model}' is not an LLM; choose one that can follow the judging prompt")
        checker = FallbackChecker(LLMClaimChecker(generator.complete), SupportScoreChecker(thresholds, reranker))
        FALLBACK_CHECKERS.append(checker)
        return ClaimVerifier(rules, checker)
    raise SystemExit(f"unknown verifier '{name}' (rules, lexical, claims, llm)")


def make_reranker(settings: Settings) -> Reranker:
    from app.rag.rerank import RERANKERS

    return CachedReranker(RERANKERS.create("fastembed", model=settings.reranker_model))


# ---------------- reporting ----------------
def pct(x: float | None) -> str:
    return "  n/a" if x is None else f"{x * 100:5.1f}%"


def render(results_by_name: dict[str, list], show_failures: bool) -> str:
    out = []
    head = f"{'verifier':<10}{'split':<6}{'n':>4}  {'catches faulty':>14} {'false alarms':>13} {'precision':>10} {'accuracy':>9} {'F1':>7}"
    out += [head, "-" * len(head)]
    for name, results in results_by_name.items():
        splits = sorted({r[0].split for r in results})
        for label, subset in [("all", results)] + ([(sp, [r for r in results if r[0].split == sp]) for sp in splits] if splits != ["holdout"] else []):
            m = confusion(subset)
            out.append(f"{name:<10}{label:<6}{m['n']:>4}  {pct(m['recall']):>14} {pct(m['false_alarm_rate']):>13} {pct(m['precision']):>10} {pct(m['accuracy']):>9} {pct(m['f1']):>7}")
    faults = sorted({c.fault for res in results_by_name.values() for c, _ in res if not c.supported})
    out += ["", "recall by fault type (caught/total, all cases):"]
    out.append(f"  {'fault':<20}" + "".join(f"{n:>14}" for n in results_by_name))
    for f in faults:
        row = f"  {f:<20}"
        for results in results_by_name.values():
            caught, total = per_fault_recall(results).get(f, (0, 0))
            row += f"{caught:>9}/{total:<4}"
        out.append(row)
    if show_failures:
        for name, results in results_by_name.items():
            misses = [(c, v) for c, v in results if (not c.supported and v.passed) or (c.supported and not v.passed)]
            out += ["", f"{name}: {len(misses)} wrong verdict(s)"]
            for c, v in misses:
                kind = "MISSED " if not c.supported else "FALSE ALARM"
                out.append(f"  - {kind} [{c.fault}] {c.id}: {c.answer}")
                if not c.supported:
                    out.append("      verifier said: passed")
                else:
                    out.append(f"      verifier said: {v.reason}")
    return "\n".join(out)


def calibrate(cases: list[VerifierCase], chunks: dict, settings: Settings, reranker: Reranker) -> tuple[SupportThresholds, list]:
    """Grid search on the dev split only. Maximizes balanced accuracy, preferring fewer false alarms on ties."""
    dev = [c for c in cases if c.split == "dev"]
    rules = CitationVerifier(settings.min_citation_coverage)
    best, board = None, []
    for lex, ce in product([0.3, 0.4, 0.5, 0.6, 0.7, 0.8], [0.0005, 0.001, 0.005, 0.01, 0.03, 0.1, 0.3]):
        thr = SupportThresholds(min_lexical=lex, min_cross_encoder=ce)
        m = confusion(run_verifier(ClaimVerifier(rules, SupportScoreChecker(thr, reranker)), dev, chunks))
        key = (m["balanced_accuracy"], -m["false_alarm_rate"], lex, ce)
        board.append((key, thr, m))
        if best is None or key > best[0]:
            best = (key, thr, m)
    board.sort(key=lambda b: b[0], reverse=True)
    return best[1], board[:5]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--verifiers", default="rules,lexical,claims")
    p.add_argument("--calibrate", action="store_true", help="grid-search thresholds on the dev split, then report all verifiers with them")
    p.add_argument("--min-lexical", type=float, default=SupportThresholds.min_lexical)
    p.add_argument("--min-cross-encoder", type=float, default=SupportThresholds.min_cross_encoder)
    p.add_argument("--cases", choices=["dev", "holdout"], default="dev", help="dev: eval/verifier_cases.json; holdout: eval/verifier_holdout.json")
    p.add_argument("--llm", default=None, help="model id for the 'llm' verifier")
    p.add_argument("--limit", type=int, default=None, help="evaluate only an evenly spaced sample of this many cases (for live LLM checks)")
    p.add_argument("--failures", action="store_true")
    p.add_argument("--json", nargs="?", const="auto")
    args = p.parse_args()

    settings = Settings()
    cases = load_cases(HOLDOUT_PATH if args.cases == "holdout" else CASES_PATH)
    if args.limit:
        step = max(1, len(cases) // args.limit)
        cases = cases[::step][: args.limit]
    chunks = corpus_chunks()
    names = [n.strip() for n in args.verifiers.split(",")]
    reranker = make_reranker(settings) if any(n in ("claims", "llm") for n in names) or args.calibrate else None
    thresholds = SupportThresholds(min_lexical=args.min_lexical, min_cross_encoder=args.min_cross_encoder)

    if args.calibrate:
        thresholds, top = calibrate(cases, chunks, settings, reranker)
        print("calibration on the dev split (balanced accuracy, false-alarm rate): top thresholds")
        for key, thr, m in top:
            print(f"  min_lexical={thr.min_lexical:<4} min_cross_encoder={thr.min_cross_encoder:<7} -> {pct(m['balanced_accuracy'])}  false alarms {pct(m['false_alarm_rate'])}")
        print(f"chosen: min_lexical={thresholds.min_lexical}, min_cross_encoder={thresholds.min_cross_encoder}\n")

    results = {n: run_verifier(build_verifier(n, thresholds, settings, args.llm, reranker), cases, chunks) for n in names}
    print(render(results, args.failures))
    for checker in FALLBACK_CHECKERS:
        print(f"\nLLM judge fallbacks to the offline checker: {checker.fallbacks} of {len(cases)} answers")

    if args.json:
        path = EVAL_DIR / "reports" / "verifier.json" if args.json == "auto" else args.json
        payload = {
            "thresholds": {"min_lexical": thresholds.min_lexical, "min_cross_encoder": thresholds.min_cross_encoder},
            "verifiers": {n: {"all": confusion(r), "dev": confusion([x for x in r if x[0].split == "dev"]), "test": confusion([x for x in r if x[0].split == "test"]), "per_fault_recall": per_fault_recall(r)} for n, r in results.items()},
        }
        open(path, "w", encoding="utf-8").write(json.dumps(payload, indent=2))
        print(f"\nreport written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
