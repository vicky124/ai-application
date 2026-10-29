"""Qdrant-backed store. Each chunk has a named dense vector and, in hybrid mode, a named sparse (BM25) vector.
Search enforces the status and role filters inside Qdrant; hybrid mode fuses dense and sparse rankings with RRF."""
import math
import uuid

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient, models

from app.domain import Source
from app.interfaces import SparseEmbedder, SparseVec

DENSE = "dense"
SPARSE = "sparse"


def _eq(key: str, value: str) -> models.FieldCondition:
    return models.FieldCondition(key=f"metadata.{key}", match=models.MatchValue(value=value))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class QdrantPolicyStore:
    def __init__(
        self,
        client: QdrantClient,
        collection: str,
        embeddings: Embeddings,
        sparse: SparseEmbedder | None = None,
        fetch_k: int = 20,
    ):
        self._client = client
        self._collection = collection
        self._embeddings = embeddings
        self._sparse = sparse
        self._fetch_k = fetch_k  # candidates pulled from each ranking before fusion
        if not client.collection_exists(collection):
            dim = len(embeddings.embed_query("probe"))
            client.create_collection(
                collection,
                vectors_config={DENSE: models.VectorParams(size=dim, distance=models.Distance.COSINE)},
                sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)} if sparse else None,
            )
            for field in ("doc_id", "status", "allowed_roles"):
                try:  # indexes only matter (and are only supported) against a server
                    client.create_payload_index(collection, f"metadata.{field}", models.PayloadSchemaType.KEYWORD)
                except Exception:
                    pass

    @property
    def hybrid(self) -> bool:
        return self._sparse is not None

    def close(self) -> None:
        self._client.close()

    # ---- write side (VectorIndex) ----
    def add_vectors(
        self, docs: list[Document], vectors: list[list[float]], sparse_vectors: list[SparseVec] | None = None
    ) -> list[str]:
        """Upsert pre-computed vectors; the payload keeps the page_content/metadata layout used since Phase 1."""
        if self._sparse is not None and sparse_vectors is None:
            raise ValueError("hybrid store needs sparse vectors for every chunk")
        ids = [str(uuid.uuid4()) for _ in docs]
        points = []
        for i, (pid, d) in enumerate(zip(ids, docs)):
            vector: dict = {DENSE: vectors[i]}
            if sparse_vectors is not None:
                indices, values = sparse_vectors[i]
                vector[SPARSE] = models.SparseVector(indices=indices, values=values)
            points.append(models.PointStruct(id=pid, vector=vector, payload={"page_content": d.page_content, "metadata": d.metadata}))
        self._client.upsert(self._collection, points=points)
        return ids

    def count_chunks(self, doc_id: str) -> int:
        return self._client.count(
            self._collection, count_filter=models.Filter(must=[_eq("doc_id", doc_id)]), exact=True
        ).count

    def delete(self, doc_id: str) -> None:
        self._client.delete(
            self._collection, points_selector=models.FilterSelector(filter=models.Filter(must=[_eq("doc_id", doc_id)]))
        )

    # ---- read side (Retriever / VectorStore) ----
    def search(self, query: str, role: str, k: int) -> list[Source]:
        flt = models.Filter(
            must=[
                _eq("status", "active"),
                models.FieldCondition(key="metadata.allowed_roles", match=models.MatchAny(any=[role, "all"])),
            ]
        )
        dense_q = self._embeddings.embed_query(query)
        indices, values = self._sparse.embed_query(query) if self._sparse else ([], [])

        if not indices:  # dense only (also when the question has no usable keywords)
            points = self._client.query_points(
                self._collection, query=dense_q, using=DENSE, query_filter=flt, limit=k, with_payload=True
            ).points
            return [self._source(p, score=p.score, relevance=p.score) for p in points]

        n = max(k, self._fetch_k)
        points = self._client.query_points(
            self._collection,
            prefetch=[
                models.Prefetch(query=dense_q, using=DENSE, filter=flt, limit=n),
                models.Prefetch(query=models.SparseVector(indices=indices, values=values), using=SPARSE, filter=flt, limit=n),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=flt,
            limit=k,
            with_payload=True,
            with_vectors=[DENSE],
        ).points
        # Fused rank scores are not comparable across questions, so relevance stays the dense cosine similarity.
        return [self._source(p, score=p.score, relevance=_cosine(dense_q, p.vector[DENSE])) for p in points]

    @staticmethod
    def _source(point, score: float, relevance: float) -> Source:
        d, m = point.payload["page_content"], point.payload["metadata"]
        return Source(
            doc_id=m["doc_id"],
            title=m["title"],
            section=m.get("section", ""),
            page=m.get("page"),
            version=m.get("version", ""),
            text=d,
            score=float(score),
            relevance=float(relevance),
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
