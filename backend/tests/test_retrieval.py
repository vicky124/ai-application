"""Hybrid retrieval, reranking and relevance thresholds. Uses hash embeddings and the overlap reranker, so it runs
offline; retrieval *quality* with the real models is measured by the evaluation suite instead."""
from dataclasses import replace

import pytest

from app.config import Settings
from app.container import Container
from app.domain import DocumentMeta, Source
from app.eval.cases import CORPUS_DIRS
from app.rag.rerank import OverlapReranker, RerankingRetriever


def make(tmp_path, mode="dense", reranker="none", **extra) -> Container:
    cfg = Settings(
        _env_file=None,
        qdrant_url=None,
        qdrant_path=str(tmp_path),
        embedding_provider="hash",
        sparse_provider="hash",
        retrieval_mode=mode,
        reranker_provider=reranker,
        autoload_samples=False,
        min_retrieval_score=0.15,
        **extra,
    )
    c = Container(cfg)
    for d in CORPUS_DIRS:
        c.ingestion.ingest_directory(str(d))
    return c


def src(i, text, score=0.5, relevance=None):
    return Source(f"d{i}", f"Doc {i}", "S", None, "1", text, score, relevance)


# ---------------- settings and domain ----------------
def test_collection_names_separate_retrieval_layouts():
    dense = Settings(_env_file=None, retrieval_mode="dense").collection_name
    hybrid = Settings(_env_file=None, retrieval_mode="hybrid").collection_name
    assert dense != hybrid and "__v2_" in dense and dense.endswith("dense") and hybrid.endswith("hybrid")


def test_threshold_follows_the_scorer():
    assert Settings(_env_file=None, reranker_provider="none", min_retrieval_score=0.4, min_rerank_score=0.002).relevance_threshold == 0.4
    assert Settings(_env_file=None, reranker_provider="fastembed", min_retrieval_score=0.4, min_rerank_score=0.002).relevance_threshold == 0.002


def test_application_defaults_are_the_measured_ones():
    f = Settings.model_fields  # class defaults; the test environment overrides some of them through env vars
    assert f["reranker_provider"].default == "fastembed" and f["retrieval_mode"].default == "dense"
    assert f["rerank_fetch_k"].default == 10 and f["min_rerank_score"].default == 0.001


def test_source_relevance_falls_back_to_score():
    assert src(1, "x", score=0.7).relevance_or_score == 0.7
    assert src(1, "x", score=0.7, relevance=0.2).relevance_or_score == 0.2


# ---------------- reranking ----------------
class FakeInner:
    def __init__(self, items):
        self.items, self.asked = items, None

    def search(self, query, role, k):
        self.asked = (query, role, k)
        return self.items


def test_reranker_reorders_truncates_and_sets_relevance():
    inner = FakeInner([src(1, "unrelated words here", 0.9), src(2, "annual leave days", 0.5), src(3, "annual leave", 0.4)])
    out = RerankingRetriever(inner, OverlapReranker(), fetch_k=10).search("annual leave days", "employee", 2)
    assert inner.asked == ("annual leave days", "employee", 10)  # asks the inner retriever for more candidates
    assert [s.doc_id for s in out] == ["d2", "d3"] and len(out) == 2
    assert out[0].score == out[0].relevance == pytest.approx(1.0)  # all query words present
    assert out[0].score > out[1].score


def test_reranker_with_no_candidates_returns_nothing():
    assert RerankingRetriever(FakeInner([]), OverlapReranker(), 10).search("q", "r", 5) == []


def test_reranker_never_changes_which_text_comes_back():
    inner = FakeInner([src(1, "alpha beta", 0.1), src(2, "gamma", 0.2)])
    out = RerankingRetriever(inner, OverlapReranker(), 10).search("alpha", "r", 5)
    assert {s.text for s in out} == {"alpha beta", "gamma"}
    assert all(replace(s, score=0, relevance=0) in [replace(i, score=0, relevance=0) for i in inner.items] for s in out)


def test_reranked_abstention_uses_the_reranker_score(tmp_path):
    c = make(tmp_path, reranker="overlap", min_rerank_score=0.4)
    related = c.agent.run("How many days of annual leave do I get?", "employee", "extractive")
    unrelated = c.agent.run("how do I bake sourdough bread", "employee", "extractive")
    assert not related["abstained"] and related["sources"][0].doc_id == "leave-policy"
    assert unrelated["abstained"] and unrelated["abstain_reason"] == "no relevant sources"
    assert "threshold 0.4 " in related["trace"][1]  # the trace reports the threshold in force
    c.store.close()


# ---------------- hybrid store ----------------
def test_hybrid_store_returns_cosine_relevance_and_fused_score(tmp_path):
    c = make(tmp_path, mode="hybrid")
    assert c.store.hybrid
    hits = c.store.search("What is the gift limit from vendors?", "employee", 5)
    assert hits and hits[0].doc_id == "code-of-conduct"
    assert all(0.0 <= h.relevance <= 1.0 for h in hits)
    assert hits[0].score != hits[0].relevance  # rank-fusion score is kept apart from the comparable relevance
    c.store.close()


def test_hybrid_finds_exact_identifiers(tmp_path):
    c = make(tmp_path, mode="hybrid")
    hits = c.store.search("What does policy code SEC-9 cover?", "employee", 3)
    assert hits[0].doc_id == "forms-and-codes"
    c.store.close()


def test_hybrid_search_still_enforces_role_and_status_filters(tmp_path):
    c = make(tmp_path, mode="hybrid")
    employee = c.store.search("What are the stages of the disciplinary procedure, written warning?", "employee", 10)
    hr = c.store.search("What are the stages of the disciplinary procedure, written warning?", "hr", 10)
    assert "disciplinary-procedure" not in {s.doc_id for s in employee}
    assert "disciplinary-procedure" in {s.doc_id for s in hr}
    superseded = c.store.search("annual leave 18 days cannot be carried forward", "employee", 20)
    assert "leave-policy-2019" not in {s.doc_id for s in superseded}  # inactive documents are never retrievable
    c.store.close()


def test_hybrid_store_requires_sparse_vectors_on_write(tmp_path):
    from langchain_core.documents import Document

    c = make(tmp_path, mode="hybrid")
    with pytest.raises(ValueError, match="sparse"):
        c.store.add_vectors([Document(page_content="x", metadata={})], [[0.0] * 384])
    c.store.close()


def test_dense_store_has_no_keyword_vectors(tmp_path):
    c = make(tmp_path, mode="dense")
    assert not c.store.hybrid
    assert c.store.search("gift limit", "employee", 3)[0].relevance is not None
    c.store.close()


# ---------------- ingestion shows keyword vectors ----------------
@pytest.mark.parametrize("mode,expect_keywords", [("dense", False), ("hybrid", True)])
def test_pipeline_embed_stage_reports_keyword_vectors(tmp_path, mode, expect_keywords):
    c = make(tmp_path, mode=mode)
    events = list(c.pipeline.run("p.md", b"# T\n\nBody text about retention and deletion.\n", DocumentMeta("probe", "Probe")))
    embed = next(e for e in events if e["type"] == "step" and e["id"] == "embed" and e["status"] == "done")["details"]
    assert ("keyword_model" in embed) is expect_keywords
    if expect_keywords:
        assert embed["keyword_vectors"] == embed["vectors"] and "keyword_terms_per_chunk" in embed
    assert events[-1]["type"] == "complete"
    c.store.close()
