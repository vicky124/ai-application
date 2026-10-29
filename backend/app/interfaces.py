"""Small, role-specific contracts (Interface Segregation). Consumers depend on these, never on concrete classes
(Dependency Inversion). Any implementation can be substituted without changing callers (Liskov)."""
from typing import Protocol

from langchain_core.documents import Document

from app.domain import GuardResult, ParsedPage, Source, Verification


class DocumentParser(Protocol):
    def parse(self, data: bytes) -> list[ParsedPage]: ...


class VectorStore(Protocol):
    def add(self, docs: list[Document]) -> None: ...
    def search(self, query: str, role: str, k: int) -> list[Source]: ...
    def delete(self, doc_id: str) -> None: ...
    def list_documents(self) -> list[dict]: ...


class VectorIndex(Protocol):
    """Write side used by the ingestion pipeline (separate from the read-side VectorStore: ISP)."""

    def add_vectors(self, docs: list[Document], vectors: list[list[float]]) -> list[str]: ...
    def delete(self, doc_id: str) -> None: ...
    def count_chunks(self, doc_id: str) -> int: ...
    def search(self, query: str, role: str, k: int) -> list[Source]: ...


class AnswerGenerator(Protocol):
    """Produces a cited answer from sources; returns INSUFFICIENT_CONTEXT when it cannot answer."""

    def generate(self, question: str, sources: list[Source]) -> str: ...


class Verifier(Protocol):
    def verify(self, answer: str, sources: list[Source]) -> Verification: ...


class InputGuard(Protocol):
    def check(self, text: str) -> GuardResult: ...
