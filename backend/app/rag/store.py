"""Qdrant-backed VectorStore built on langchain-qdrant. Enforces status + role filters at query time."""
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient, models

from app.domain import Source


def _eq(key: str, value: str) -> models.FieldCondition:
    return models.FieldCondition(key=f"metadata.{key}", match=models.MatchValue(value=value))


class QdrantPolicyStore:
    def __init__(self, client: QdrantClient, collection: str, embeddings: Embeddings):
        self._client = client
        self._collection = collection
        self._embeddings = embeddings
        if not client.collection_exists(collection):
            dim = len(embeddings.embed_query("probe"))
            client.create_collection(
                collection, vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE)
            )
            for field in ("doc_id", "status", "allowed_roles"):
                try:  # indexes only matter (and are only supported) against a server
                    client.create_payload_index(collection, f"metadata.{field}", models.PayloadSchemaType.KEYWORD)
                except Exception:
                    pass
        self._vs = QdrantVectorStore(client=client, collection_name=collection, embedding=embeddings)

    def add(self, docs: list[Document]) -> None:
        if docs:
            self._vs.add_documents(docs)

    def search(self, query: str, role: str, k: int) -> list[Source]:
        flt = models.Filter(
            must=[
                _eq("status", "active"),
                models.FieldCondition(key="metadata.allowed_roles", match=models.MatchAny(any=[role, "all"])),
            ]
        )
        results = self._vs.similarity_search_with_score(query, k=k, filter=flt)
        return [
            Source(
                doc_id=d.metadata["doc_id"],
                title=d.metadata["title"],
                section=d.metadata.get("section", ""),
                page=d.metadata.get("page"),
                version=d.metadata.get("version", ""),
                text=d.page_content,
                score=float(score),
            )
            for d, score in results
        ]

    def delete(self, doc_id: str) -> None:
        self._client.delete(
            self._collection, points_selector=models.FilterSelector(filter=models.Filter(must=[_eq("doc_id", doc_id)]))
        )

    def list_documents(self) -> list[dict]:
        docs: dict[str, dict] = {}
        offset = None
        while True:
            points, offset = self._client.scroll(self._collection, limit=256, offset=offset, with_payload=True)
            for p in points:
                m = p.payload["metadata"]
                d = docs.setdefault(
                    m["doc_id"],
                    {k: m.get(k) for k in ("doc_id", "title", "department", "version", "status", "allowed_roles")}
                    | {"chunks": 0},
                )
                d["chunks"] += 1
            if offset is None:
                break
        return sorted(docs.values(), key=lambda x: x["title"])
