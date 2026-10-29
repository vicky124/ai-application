"""Index maintenance.

    python -m app.rag.manage reindex [--source COLLECTION]   copy documents into the current collection layout
    python -m app.rag.manage ingest-samples                  load data/sample_docs into the current collection

`reindex` re-embeds the stored chunk text, so no original files are needed. Use it after changing the embedding model
or the retrieval layout (collection names encode both). Stop the API first when Qdrant runs in embedded mode (one
process at a time). The source collection is left untouched as a backup.
"""
import argparse
import re
import sys
from collections import defaultdict

from langchain_core.documents import Document

from app.config import settings
from app.container import Container


def legacy_collection_name() -> str:
    """Phase 1 name: no layout suffix and an unnamed dense vector."""
    slug = re.sub(r"[^a-z0-9]+", "_", settings.embedding_model.lower()).strip("_")
    return f"{settings.qdrant_collection_prefix}__{settings.embedding_provider}_{slug}"


def reindex(source: str) -> int:
    c = Container(settings)
    client = c.store._client
    target = settings.collection_name
    if source == target:
        print("Source and target collection are the same; nothing to do.", file=sys.stderr)
        return 1
    if not client.collection_exists(source):
        print(f"Source collection '{source}' does not exist.", file=sys.stderr)
        return 1

    by_doc: dict[str, list[Document]] = defaultdict(list)
    offset = None
    while True:
        points, offset = client.scroll(source, limit=256, offset=offset, with_payload=True)
        for p in points:
            by_doc[p.payload["metadata"]["doc_id"]].append(
                Document(page_content=p.payload["page_content"], metadata=p.payload["metadata"])
            )
        if offset is None:
            break

    print(f"{source} -> {target}  ({settings.retrieval_mode} retrieval, {len(by_doc)} documents)")
    total = 0
    for doc_id, docs in sorted(by_doc.items()):
        texts = [d.page_content for d in docs]
        dense = c.embeddings.embed_documents(texts)
        sparse = c.sparse.embed_documents(texts) if c.sparse else None
        c.store.delete(doc_id)  # replace, so running it twice never duplicates
        c.store.add_vectors(docs, dense, sparse)
        total += len(docs)
        print(f"  {doc_id:<28} {len(docs):>3} chunks  status={docs[0].metadata.get('status')}")
    print(f"Done: {total} chunks. The source collection was not modified.")
    c.store.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reindex")
    r.add_argument("--source", default=None, help="collection to copy from (default: the Phase 1 collection)")
    sub.add_parser("ingest-samples")
    args = parser.parse_args()

    if args.cmd == "reindex":
        return reindex(args.source or legacy_collection_name())
    c = Container(settings)
    for doc_id, n in c.ingestion.ingest_directory(settings.sample_docs_dir).items():
        print(f"  {doc_id:<28} {n:>3} chunks")
    c.store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
