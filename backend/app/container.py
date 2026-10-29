"""Composition root: the only place that knows concrete classes and wires them together."""
from functools import lru_cache

from qdrant_client import QdrantClient

from app.agents.components import CitationVerifier, RegexInputGuard
from app.agents.graph import PolicyAgent
from app.config import Settings, settings
from app.providers.generators import ModelCatalog
from app.rag.embeddings import EMBEDDINGS
from app.rag.ingest import IngestionService
from app.rag.parsers import default_parsers
from app.rag.store import QdrantPolicyStore


class Container:
    def __init__(self, cfg: Settings):
        self.settings = cfg
        client = QdrantClient(url=cfg.qdrant_url) if cfg.qdrant_url else QdrantClient(path=cfg.qdrant_path)
        embeddings = EMBEDDINGS.create(cfg.embedding_provider, model=cfg.embedding_model)
        self.store = QdrantPolicyStore(client, cfg.collection_name, embeddings)
        self.ingestion = IngestionService(self.store, default_parsers(), cfg.chunk_size, cfg.chunk_overlap)
        self.models = ModelCatalog(cfg.models, cfg)
        self.agent = PolicyAgent(
            guard=RegexInputGuard(),
            store=self.store,
            resolve_generator=self.models.get,
            verifier=CitationVerifier(cfg.min_citation_coverage),
            top_k=cfg.top_k,
            min_score=cfg.min_retrieval_score,
            max_attempts=cfg.max_generation_attempts,
        )


@lru_cache(maxsize=1)
def get_container() -> Container:
    return Container(settings)
