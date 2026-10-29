"""LangChain Embeddings implementations, selected by config through a registry."""
import hashlib
import math
import re

from langchain_core.embeddings import Embeddings

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


@EMBEDDINGS.register("hash")
def _hash(model: str) -> Embeddings:
    return HashEmbeddings()


@EMBEDDINGS.register("fastembed")
def _fastembed(model: str) -> Embeddings:
    return FastEmbedEmbeddings(model)
