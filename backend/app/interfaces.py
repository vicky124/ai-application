"""Small, role-specific contracts (Interface Segregation). Consumers depend on these, never on concrete classes
(Dependency Inversion). Any implementation can be substituted without changing callers (Liskov)."""
from typing import Protocol

from langchain_core.documents import Document

from app.domain import Claim, ClaimCheck, GuardResult, ParsedPage, Source, Verification

# A sparse vector as (indices, values), for keyword-style (BM25 / SPLADE) retrieval.
SparseVec = tuple[list[int], list[float]]


class DocumentParser(Protocol):
    def parse(self, data: bytes) -> list[ParsedPage]: ...


class Retriever(Protocol):
    """What the agent needs: the best passages for a question that this role may read."""

    def search(self, query: str, role: str, k: int) -> list[Source]: ...


class VectorStore(Retriever, Protocol):
    """Read and manage side of the index (a Retriever plus document management)."""

    def delete(self, doc_id: str) -> None: ...
    def list_documents(self) -> list[dict]: ...


class VectorIndex(Retriever, Protocol):
    """Write side used by the ingestion pipeline (separate from the read-side VectorStore: ISP)."""

    def add_vectors(
        self, docs: list[Document], vectors: list[list[float]], sparse_vectors: list[SparseVec] | None = None
    ) -> list[str]: ...
    def delete(self, doc_id: str) -> None: ...
    def count_chunks(self, doc_id: str) -> int: ...


class SparseEmbedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[SparseVec]: ...
    def embed_query(self, text: str) -> SparseVec: ...


class Reranker(Protocol):
    """Scores passages against a query with a cross-encoder. Returns probabilities in 0..1, higher is more relevant."""

    def score(self, query: str, passages: list[str]) -> list[float]: ...


class AnswerGenerator(Protocol):
    """Produces a cited answer from sources; returns INSUFFICIENT_CONTEXT when it cannot answer."""

    def generate(self, question: str, sources: list[Source], feedback: str | None = None) -> str:
        """`feedback` describes what was wrong with a previous attempt (set on retries)."""
        ...


class ClaimChecker(Protocol):
    """Judges, claim by claim, whether the cited sources support what the answer says."""

    def check(self, claims: list[Claim], sources: list[Source]) -> list[ClaimCheck]: ...


class Verifier(Protocol):
    def verify(self, answer: str, sources: list[Source]) -> Verification: ...


class InputGuard(Protocol):
    def check(self, text: str) -> GuardResult: ...
