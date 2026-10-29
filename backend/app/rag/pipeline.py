"""Observable ingestion pipeline.

`IngestionPipeline.run` is a generator of JSON-serializable events, one stage at a time:

    {"type": "plan", "doc_id", "steps": [{"id", "label"}, ...]}
    {"type": "step", "id", "status": "running"}
    {"type": "step", "id", "status": "done", "duration_ms", "details": {...}}
    {"type": "step", "id", "status": "error", "duration_ms", "error"}      # followed by "failed"
    {"type": "complete", "doc_id", "chunks"}  |  {"type": "failed", "error"}

Each stage is a small method; stages share state through a context dict. The pipeline depends only on
abstractions (VectorIndex, ParserRegistry, LangChain Embeddings), so storage and models are swappable.
"""
import hashlib
import math
import time
from dataclasses import asdict
from typing import Callable, Iterator

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.domain import DocumentMeta, ParsedPage
from app.interfaces import VectorIndex
from app.rag.chunking import chunk_text
from app.rag.parsers import ParserRegistry
from app.rag.text import clean_text, parse_frontmatter

STEPS = [
    ("receive", "Receive and validate"),
    ("parse", "Parse document"),
    ("clean", "Clean text"),
    ("chunk", "Split into chunks"),
    ("embed", "Create embeddings"),
    ("store", "Store vectors in Qdrant"),
    ("verify", "Verify index"),
]

PREVIEW_CHARS = 280
VECTOR_PREVIEW_DIMS = 8


def _clip(text: str, n: int = PREVIEW_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= n else text[:n].rstrip() + "..."


class IngestionPipeline:
    def __init__(
        self,
        index: VectorIndex,
        parsers: ParserRegistry,
        embeddings: Embeddings,
        embedding_label: str,
        collection: str,
        chunk_size: int,
        chunk_overlap: int,
    ):
        self._index = index
        self._parsers = parsers
        self._embeddings = embeddings
        self._embedding_label = embedding_label
        self._collection = collection
        self._size = chunk_size
        self._overlap = chunk_overlap
        self._stages: dict[str, Callable[[dict], dict]] = {
            "receive": self._receive,
            "parse": self._parse,
            "clean": self._clean,
            "chunk": self._chunk,
            "embed": self._embed,
            "store": self._store,
            "verify": self._verify,
        }

    def run(self, filename: str, data: bytes, meta: DocumentMeta) -> Iterator[dict]:
        ctx: dict = {"filename": filename, "data": data, "meta": meta}
        yield {"type": "plan", "doc_id": meta.doc_id, "steps": [{"id": i, "label": l} for i, l in STEPS]}
        for step_id, _ in STEPS:
            yield {"type": "step", "id": step_id, "status": "running"}
            started = time.perf_counter()
            try:
                details = self._stages[step_id](ctx)
            except Exception as e:  # surfaced to the UI; the pipeline stops at the failing stage
                ms = round((time.perf_counter() - started) * 1000)
                yield {"type": "step", "id": step_id, "status": "error", "duration_ms": ms, "error": str(e)}
                yield {"type": "failed", "error": str(e)}
                return
            ms = round((time.perf_counter() - started) * 1000)
            yield {"type": "step", "id": step_id, "status": "done", "duration_ms": ms, "details": details}
        yield {"type": "complete", "doc_id": meta.doc_id, "chunks": len(ctx["docs"])}

    # ---- stages ----
    def _receive(self, ctx: dict) -> dict:
        data: bytes = ctx["data"]
        if not data:
            raise ValueError("File is empty")
        ctx["parser"] = self._parsers.for_file(ctx["filename"])  # raises for unsupported types
        meta: DocumentMeta = ctx["meta"]
        return {
            "filename": ctx["filename"],
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()[:16],
            "parser": type(ctx["parser"]).__name__,
            "document": asdict(meta),
        }

    def _parse(self, ctx: dict) -> dict:
        pages: list[ParsedPage] = ctx["parser"].parse(ctx["data"])
        chars = sum(len(p.text) for p in pages)
        if not chars or not any(p.text.strip() for p in pages):
            raise ValueError("No extractable text found (is this a scanned document?)")
        ctx["pages"] = pages
        return {"pages": len(pages), "characters": chars, "preview": _clip(pages[0].text)}

    def _clean(self, ctx: dict) -> dict:
        pages: list[ParsedPage] = ctx["pages"]
        before = sum(len(p.text) for p in pages)
        front_matter_removed = False
        cleaned = []
        for i, p in enumerate(pages):
            text = p.text
            if i == 0:
                fm, body = parse_frontmatter(text)
                if fm:
                    front_matter_removed, text = True, body
            cleaned.append(ParsedPage(clean_text(text), p.page))
        cleaned = [p for p in cleaned if p.text]
        if not cleaned:
            raise ValueError("Document has no text after cleaning")
        ctx["pages"] = cleaned
        after = sum(len(p.text) for p in cleaned)
        return {
            "characters_before": before,
            "characters_after": after,
            "removed": before - after,
            "front_matter_removed": front_matter_removed,
            "operations": ["normalize line endings", "strip control characters", "trim trailing spaces", "collapse blank lines"],
        }

    def _chunk(self, ctx: dict) -> dict:
        meta: DocumentMeta = ctx["meta"]
        docs: list[Document] = []
        for page in ctx["pages"]:
            for ch in chunk_text(page.text, self._size, self._overlap, page.page):
                docs.append(Document(page_content=ch.text, metadata={**asdict(meta), "section": ch.section, "page": ch.page}))
        if not docs:
            raise ValueError("No chunks produced")
        ctx["docs"] = docs
        sizes = [len(d.page_content) for d in docs]
        sections = list(dict.fromkeys(d.metadata["section"] for d in docs))
        return {
            "chunks": len(docs),
            "chunk_size_setting": self._size,
            "chunk_overlap_setting": self._overlap,
            "chars_min": min(sizes),
            "chars_avg": round(sum(sizes) / len(sizes)),
            "chars_max": max(sizes),
            "sections": sections[:12],
            "previews": [
                {"index": i, "section": d.metadata["section"], "page": d.metadata["page"], "chars": len(d.page_content), "text": _clip(d.page_content)}
                for i, d in enumerate(docs[:3])
            ],
        }

    def _embed(self, ctx: dict) -> dict:
        docs: list[Document] = ctx["docs"]
        vectors = self._embeddings.embed_documents([d.page_content for d in docs])
        ctx["vectors"] = vectors
        first = vectors[0]
        return {
            "model": self._embedding_label,
            "vectors": len(vectors),
            "dimensions": len(first),
            "first_vector_preview": [round(float(x), 4) for x in first[:VECTOR_PREVIEW_DIMS]],
            "first_vector_l2_norm": round(math.sqrt(sum(x * x for x in first)), 4),
        }

    def _store(self, ctx: dict) -> dict:
        meta: DocumentMeta = ctx["meta"]
        docs, vectors = ctx["docs"], ctx["vectors"]
        previous = self._index.count_chunks(meta.doc_id)
        self._index.delete(meta.doc_id)
        ids = self._index.add_vectors(docs, vectors)
        return {
            "collection": self._collection,
            "previous_chunks_removed": previous,
            "points_upserted": len(ids),
            "point_id_sample": ids[:2],
            "payload_fields": sorted({"page_content", "metadata"}) + [f"metadata.{k}" for k in docs[0].metadata],
        }

    def _verify(self, ctx: dict) -> dict:
        meta: DocumentMeta = ctx["meta"]
        docs = ctx["docs"]
        stored = self._index.count_chunks(meta.doc_id)
        if stored != len(docs):
            raise RuntimeError(f"Index has {stored} chunks for '{meta.doc_id}', expected {len(docs)}")
        result: dict = {"chunks_in_index": stored, "expected": len(docs)}
        if meta.status != "active":
            result["self_retrieval"] = {"skipped": f"document status is '{meta.status}' (inactive documents are not searchable)"}
            return result
        role = next((r for r in meta.allowed_roles if r != "all"), "all")
        hits = self._index.search(docs[0].page_content, role, 3)
        top = hits[0] if hits else None
        result["self_retrieval"] = {
            "query": "text of chunk 0",
            "as_role": role,
            "top_doc_id": top.doc_id if top else None,
            "top_score": round(top.score, 3) if top else None,
            "passed": bool(top and top.doc_id == meta.doc_id),
        }
        return result
