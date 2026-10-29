"""Builds the real production stack (app.container.Container) on a throwaway Qdrant folder and loads the corpus,
so the evaluation measures exactly what runs in the application, one configuration at a time."""
import tempfile
from dataclasses import dataclass

from app.config import Settings
from app.container import Container
from app.eval.cases import CORPUS_DIRS


@dataclass(frozen=True)
class StackConfig:
    retrieval: str = "dense"  # dense | hybrid
    rerank: str = "none"  # none | fastembed | overlap (the application default is fastembed)
    embedding_provider: str = "fastembed"  # fastembed | hash (offline, not semantic)
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    model_id: str = "extractive"
    top_k: int = 5
    fetch_k: int = 10  # candidates passed to the reranker
    verifier: str = "rules"  # rules | claims | llm (the application default is claims)
    min_score: float | None = None  # relevance threshold; None keeps the application's default for this configuration

    @property
    def label(self) -> str:
        return f"{self.retrieval}+{self.rerank}" + ("" if self.verifier == "rules" else f"+{self.verifier}")


class Stack:
    def __init__(self, cfg: StackConfig):
        self.cfg = cfg
        self._tmp = tempfile.TemporaryDirectory(prefix="eval_qdrant_")
        overrides = dict(
            qdrant_url=None,
            qdrant_path=self._tmp.name,
            embedding_provider=cfg.embedding_provider,
            embedding_model=cfg.embedding_model,
            top_k=cfg.top_k,
            rerank_fetch_k=cfg.fetch_k,
            autoload_samples=False,
            retrieval_mode=cfg.retrieval,
            reranker_provider=cfg.rerank,
            verifier_mode=cfg.verifier,
        )
        if cfg.min_score is not None:
            overrides["min_retrieval_score"] = cfg.min_score
            overrides["min_rerank_score"] = cfg.min_score
        self.settings = Settings(**overrides)  # still reads backend/.env (e.g. the Gemini key), then overrides
        self.container = Container(self.settings)
        self.chunks = {}
        for directory in CORPUS_DIRS:
            self.chunks.update(self.container.ingestion.ingest_directory(str(directory)))

    @property
    def retriever(self):
        """What the agent queries: the store, or a decorated store (for example with reranking)."""
        return getattr(self.container, "retriever", self.container.store)

    def close(self) -> None:
        self.container.store.close()
        self._tmp.cleanup()


def build_stack(cfg: StackConfig) -> Stack:
    return Stack(cfg)
