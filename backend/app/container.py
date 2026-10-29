"""Composition root: the only place that knows concrete classes and wires them together."""
from functools import lru_cache

from qdrant_client import QdrantClient

from app.agents.components import CitationVerifier, RegexInputGuard
from app.agents.graph import PolicyAgent
from app.config import Settings, settings
from app.providers.generators import ModelCatalog
from app.rag.embeddings import EMBEDDINGS, SPARSE
from app.rag.ingest import IngestionService
from app.rag.parsers import default_parsers
from app.rag.pipeline import IngestionPipeline
from app.rag.rerank import RERANKERS, RerankingRetriever
from app.rag.store import QdrantPolicyStore


class Container:
    def __init__(self, cfg: Settings):
        self.settings = cfg
        client = QdrantClient(url=cfg.qdrant_url) if cfg.qdrant_url else QdrantClient(path=cfg.qdrant_path)
        embeddings = EMBEDDINGS.create(cfg.embedding_provider, model=cfg.embedding_model)
        sparse = SPARSE.create(cfg.sparse_provider, model=cfg.sparse_model) if cfg.retrieval_mode == "hybrid" else None
        self.embeddings, self.sparse = embeddings, sparse
        self.store = QdrantPolicyStore(client, cfg.collection_name, embeddings, sparse, cfg.rerank_fetch_k)

        # What the agent queries: the store, optionally decorated with a cross-encoder reranker.
        self.retriever = self.store
        if cfg.reranker_provider != "none":
            reranker = RERANKERS.create(cfg.reranker_provider, model=cfg.reranker_model)
            self.retriever = RerankingRetriever(self.store, reranker, cfg.rerank_fetch_k)

        self.pipeline = IngestionPipeline(
            index=self.store,
            parsers=default_parsers(),
            embeddings=embeddings,
            embedding_label=f"{cfg.embedding_provider}:{cfg.embedding_model}",
            collection=cfg.collection_name,
            chunk_size=cfg.chunk_size,
            chunk_overlap=cfg.chunk_overlap,
            sparse=sparse,
            sparse_label=f"{cfg.sparse_provider}:{cfg.sparse_model}" if sparse else None,
        )
        self.ingestion = IngestionService(self.pipeline)
        self.models = ModelCatalog(cfg.models, cfg)
        self.agent = PolicyAgent(
            guard=RegexInputGuard(),
            retriever=self.retriever,
            resolve_generator=self.models.get,
            verifier=CitationVerifier(cfg.min_citation_coverage),
            top_k=cfg.top_k,
            min_score=cfg.relevance_threshold,
            max_attempts=cfg.max_generation_attempts,
        )


@lru_cache(maxsize=1)
def get_container() -> Container:
    return Container(settings)
