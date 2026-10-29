"""Pure metric helpers (no I/O), so they can be unit-tested on their own."""
import math
import re

_CITE = re.compile(r"\[(\d+)\]")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def facts_found(answer: str, facts: tuple[str, ...] | list[str]) -> tuple[list[str], list[str]]:
    """Returns (found, missing) for case-insensitive substring matches."""
    text = normalize(answer)
    found = [f for f in facts if normalize(f) in text]
    return found, [f for f in facts if f not in found]


def cited_numbers(answer: str) -> list[int]:
    return [int(n) for n in _CITE.findall(answer)]


def citation_precision(answer: str, source_doc_ids: list[str], expected_docs: tuple[str, ...]) -> float | None:
    """Share of distinct valid citations that point at an expected document; None when nothing is cited."""
    cited = sorted({n for n in cited_numbers(answer) if 1 <= n <= len(source_doc_ids)})
    if not cited:
        return None
    return sum(1 for n in cited if source_doc_ids[n - 1] in expected_docs) / len(cited)


def first_rank(expected_docs: tuple[str, ...], retrieved_doc_ids: list[str]) -> int | None:
    """1-based rank of the first retrieved chunk that belongs to an expected document."""
    for i, doc_id in enumerate(retrieved_doc_ids, 1):
        if doc_id in expected_docs:
            return i
    return None


def reciprocal_rank(expected_docs: tuple[str, ...], retrieved_doc_ids: list[str]) -> float:
    rank = first_rank(expected_docs, retrieved_doc_ids)
    return 1.0 / rank if rank else 0.0


def doc_recall(expected_docs: tuple[str, ...], retrieved_doc_ids: list[str]) -> float:
    return sum(1 for d in expected_docs if d in retrieved_doc_ids) / len(expected_docs) if expected_docs else 1.0


def mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)]


def best_threshold(answerable_scores: list[float], refuse_scores: list[float]) -> tuple[float, float]:
    """Cut-off that best separates questions that should be answered (score >= t) from ones that should be refused.
    Returns (threshold, balanced accuracy). Used to re-tune the relevance threshold when the scoring changes."""
    candidates = sorted(set(answerable_scores + refuse_scores))
    if not candidates:
        return 0.0, 0.0
    best = (candidates[0], -1.0)
    for lo, hi in zip(candidates, candidates[1:] + [candidates[-1] + 1e-6]):
        t = (lo + hi) / 2 if hi != lo else lo
        tpr = sum(s >= t for s in answerable_scores) / max(len(answerable_scores), 1)
        tnr = sum(s < t for s in refuse_scores) / max(len(refuse_scores), 1)
        acc = (tpr + tnr) / 2
        if acc > best[1]:
            best = (t, acc)
    return best
