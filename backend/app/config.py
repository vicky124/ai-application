"""Configuration. Model choices live here (config level) and are exposed via /api/models (app level)."""
import json
import re
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class ModelSpec(BaseModel):
    """One selectable answer-generation model."""

    id: str
    label: str
    provider: str  # key in the LLM provider registry: "ollama", "extractive", ...
    name: str | None = None  # provider-specific model name, e.g. "llama3.1:8b"
    temperature: float = 0.0
    default: bool = False


DEFAULT_MODELS = [
    ModelSpec(id="llama3.1-8b", label="Llama 3.1 8B (Ollama)", provider="ollama", name="llama3.1:8b", default=True),
    ModelSpec(id="qwen2.5-7b", label="Qwen 2.5 7B (Ollama)", provider="ollama", name="qwen2.5:7b"),
    ModelSpec(id="mistral-7b", label="Mistral 7B (Ollama)", provider="ollama", name="mistral:7b"),
    ModelSpec(id="extractive", label="No LLM (extractive, offline)", provider="extractive"),
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    # Optional JSON file with a list of ModelSpec objects; overrides DEFAULT_MODELS.
    models_config: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    # Qdrant: qdrant_url targets a server (docker compose); otherwise embedded local storage.
    qdrant_url: str | None = None
    qdrant_path: str = str(BASE_DIR / "data" / "qdrant")
    qdrant_collection_prefix: str = "policy_chunks"

    # Embeddings are fixed per collection (vector size), so they are chosen at config level only.
    embedding_provider: str = "fastembed"  # "fastembed" | "hash"
    embedding_model: str = "BAAI/bge-small-en-v1.5"

    top_k: int = 5
    min_retrieval_score: float = 0.45
    min_citation_coverage: float = 0.6
    max_generation_attempts: int = 2
    chunk_size: int = 900
    chunk_overlap: int = 150

    jwt_secret: str = "dev-only-change-me"
    jwt_expire_minutes: int = 480

    sample_docs_dir: str = str(BASE_DIR / "data" / "sample_docs")
    autoload_samples: bool = True
    cors_origins: list[str] = ["http://localhost:5173"]

    @property
    def models(self) -> list[ModelSpec]:
        if self.models_config:
            return [ModelSpec(**m) for m in json.loads(Path(self.models_config).read_text())]
        return DEFAULT_MODELS

    @property
    def collection_name(self) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", self.embedding_model.lower()).strip("_")
        return f"{self.qdrant_collection_prefix}__{self.embedding_provider}_{slug}"


settings = Settings()
