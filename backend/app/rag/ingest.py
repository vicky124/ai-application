"""IngestionService: parse -> chunk -> index. Depends only on abstractions (parsers, VectorStore)."""
from dataclasses import asdict
from pathlib import Path

from langchain_core.documents import Document

from app.domain import DocumentMeta
from app.interfaces import VectorStore
from app.rag.chunking import chunk_text
from app.rag.parsers import ParserRegistry


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Minimal `---\\nkey: value\\n---` header parser."""
    if not text.startswith("---"):
        return {}, text
    _, header, body = text.split("---", 2)
    meta = {}
    for line in header.strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, body.lstrip("\n")


class IngestionService:
    def __init__(self, store: VectorStore, parsers: ParserRegistry, chunk_size: int, chunk_overlap: int):
        self._store = store
        self._parsers = parsers
        self._size = chunk_size
        self._overlap = chunk_overlap

    def ingest_bytes(self, filename: str, data: bytes, meta: DocumentMeta) -> int:
        """Index a document; re-ingesting the same doc_id replaces it. Returns chunk count."""
        pages = self._parsers.for_file(filename).parse(data)
        docs = []
        for page in pages:
            for ch in chunk_text(page.text, self._size, self._overlap, page.page):
                docs.append(
                    Document(page_content=ch.text, metadata={**asdict(meta), "section": ch.section, "page": ch.page})
                )
        self._store.delete(meta.doc_id)
        self._store.add(docs)
        return len(docs)

    def ingest_directory(self, directory: str) -> dict[str, int]:
        results = {}
        for path in sorted(Path(directory).glob("*")):
            if path.suffix.lower() not in (".md", ".txt"):
                continue
            fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            meta = DocumentMeta(
                doc_id=fm.get("doc_id", path.stem),
                title=fm.get("title", path.stem.replace("-", " ").title()),
                department=fm.get("department", "General"),
                version=fm.get("version", "1.0"),
                status=fm.get("status", "active"),
                allowed_roles=[r.strip() for r in fm.get("allowed_roles", "all").split(",")],
            )
            results[meta.doc_id] = self.ingest_bytes(path.name, body.encode(), meta)
        return results
