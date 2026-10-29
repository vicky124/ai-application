"""LangChain Embeddings implementations, selected by config through a registry."""
import hashlib
import math
import re

from langchain_core.embeddings import Embeddings

from app.interfaces import SparseEmbedder, SparseVec
from app.registry import Registry

EMBEDDINGS: Registry[Embeddings] = Registry("embedding provider")


class HashEmbeddings(Embeddings):
    """Deterministic bag-of-words hashing embeddings. Offline fallback and test double."""

    dim = 384

    def _one(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0 if (h >> 8) % 2 else -1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._one(text)


class FastEmbedEmbeddings(Embeddings):
    """Open-source ONNX embedding models (e.g. BAAI/bge-small-en-v1.5), run locally."""

    def __init__(self, model: str):
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model)
        self.dim = len(next(iter(self._model.embed(["probe"]))))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.query_embed(text))).tolist()


SPARSE: Registry[SparseEmbedder] = Registry("sparse embedding provider")


class Bm25Sparse:
    """BM25 term-weight vectors via FastEmbed ('Qdrant/bm25'). Qdrant applies the IDF part at query time."""

    def __init__(self, model: str):
        from fastembed import SparseTextEmbedding

        self._model = SparseTextEmbedding(model_name=model)

    @staticmethod
    def _vec(e) -> SparseVec:
        return e.indices.tolist(), e.values.tolist()

    def embed_documents(self, texts: list[str]) -> list[SparseVec]:
        return [self._vec(e) for e in self._model.embed(texts)]

    def embed_query(self, text: str) -> SparseVec:
        return self._vec(next(iter(self._model.query_embed(text))))


class HashSparse:
    """Term-frequency vectors over hashed tokens. Offline fallback and test double (no stemming or stop words)."""

    BUCKETS = 1 << 18

    def _one(self, text: str) -> SparseVec:
        counts: dict[int, float] = {}
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            idx = int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.BUCKETS
            counts[idx] = counts.get(idx, 0.0) + 1.0
        return list(counts), list(counts.values())

    def embed_documents(self, texts: list[str]) -> list[SparseVec]:
        return [self._one(t) for t in texts]

    def embed_query(self, text: str) -> SparseVec:
        return self._one(text)


@SPARSE.register("fastembed")
def _bm25(model: str) -> SparseEmbedder:
    return Bm25Sparse(model)


@SPARSE.register("hash")
def _hash_sparse(model: str) -> SparseEmbedder:
    return HashSparse()


@EMBEDDINGS.register("hash")
def _hash(model: str) -> Embeddings:
    return HashEmbeddings()


@EMBEDDINGS.register("fastembed")
def _fastembed(model: str) -> Embeddings:
    return FastEmbedEmbeddings(model)
