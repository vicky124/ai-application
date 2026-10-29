"""IngestionService: convenience layer over the pipeline (blocking use, directory loading)."""
from pathlib import Path

from app.domain import DocumentMeta
from app.rag.pipeline import IngestionPipeline
from app.rag.text import parse_frontmatter


class IngestionService:
    def __init__(self, pipeline: IngestionPipeline):
        self._pipeline = pipeline

    def ingest_bytes(self, filename: str, data: bytes, meta: DocumentMeta) -> int:
        """Run the pipeline to completion. Re-ingesting the same doc_id replaces it. Returns the chunk count."""
        for event in self._pipeline.run(filename, data, meta):
            if event["type"] == "failed":
                raise ValueError(event["error"])
            if event["type"] == "complete":
                return event["chunks"]
        raise RuntimeError("Pipeline ended without a result")

    def ingest_directory(self, directory: str) -> dict[str, int]:
        results = {}
        for path in sorted(Path(directory).glob("*")):
            if path.suffix.lower() not in (".md", ".txt"):
                continue
            fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            meta = DocumentMeta(
                doc_id=fm.get("doc_id", path.stem),
                title=fm.get("title", path.stem.replace("-", " ").title()),
                department=fm.get("department", "General"),
                version=fm.get("version", "1.0"),
                status=fm.get("status", "active"),
                allowed_roles=[r.strip() for r in fm.get("allowed_roles", "all").split(",")],
            )
            results[meta.doc_id] = self.ingest_bytes(path.name, path.read_bytes(), meta)
        return results
