"""Cross-encoder reranking. A reranker reads the question and each candidate passage together, which is much more
accurate than comparing two independent embeddings, and its output is a calibrated-enough probability that the
agent can use to decide whether to answer or abstain."""
import math
import re
from dataclasses import replace

from app.domain import Source
from app.interfaces import Reranker, Retriever
from app.registry import Registry

RERANKERS: Registry[Reranker] = Registry("reranker provider")


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class FastEmbedReranker:
    """Open-source ONNX cross-encoders (default Xenova/ms-marco-MiniLM-L-6-v2, about 80 MB) run locally."""

    def __init__(self, model: str):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self._model = TextCrossEncoder(model_name=model)

    def score(self, query: str, passages: list[str]) -> list[float]:
        return [_sigmoid(float(s)) for s in self._model.rerank(query, passages)]


class OverlapReranker:
    """Share of query words found in the passage. Offline fallback and test double, not a real relevance model."""

    @staticmethod
    def _words(text: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", text.lower()))

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = self._words(query)
        return [len(q & self._words(p)) / len(q) if q else 0.0 for p in passages]


@RERANKERS.register("fastembed")
def _fastembed(model: str) -> Reranker:
    return FastEmbedReranker(model)


@RERANKERS.register("overlap")
def _overlap(model: str) -> Reranker:
    return OverlapReranker()


class RerankingRetriever:
    """Decorates any Retriever: fetches more candidates, reorders them with a reranker and keeps the best k.
    The reranker probability becomes both the score and the relevance used for the answer/abstain decision."""

    def __init__(self, inner: Retriever, reranker: Reranker, fetch_k: int):
        self._inner = inner
        self._reranker = reranker
        self._fetch_k = fetch_k

    def search(self, query: str, role: str, k: int) -> list[Source]:
        candidates = self._inner.search(query, role, max(k, self._fetch_k))
        if not candidates:
            return []
        scores = self._reranker.score(query, [c.text for c in candidates])
        ranked = sorted(zip(candidates, scores), key=lambda cs: cs[1], reverse=True)[:k]
        return [replace(c, score=s, relevance=s) for c, s in ranked]
