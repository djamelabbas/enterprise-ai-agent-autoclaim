"""P1: offline hybrid RAG, security parameters, fallback and evaluation."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from autoclaim_agent.hybrid import (
    HybridClauseRetriever, reciprocal_rank_fusion, validate_embedding,
    VertexTextEmbedder, EMBEDDING_DIM,
)
from scripts.evaluate_retrieval import metrics

GROUPS = frozenset({"gestionnaires_auto"})
DATE = "2026-10-30"
ROW = {"citation": "CG-AUTO-DEMO-2026@v1.0#BG-01", "title": "Bris de glace",
       "text": "Vitrage", "coverage_code": "BRIS_GLACE"}


class FakeEmbedder:
    def __init__(self):
        self.calls = []
    def embed(self, text, *, task_type):
        self.calls.append((text, task_type))
        return [0.5] * EMBEDDING_DIM


class FakeBigQuery:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.queries = []
    def query(self, sql, job_config, location):
        self.queries.append((sql, job_config, location))
        return SimpleNamespace(result=lambda timeout: [SimpleNamespace(items=lambda: row.items()) for row in self.rows])


def test_rrf_ranking_and_deduplication():
    a = dict(ROW)
    b = dict(ROW, citation="CG-AUTO-DEMO-2026@v1.0#CALC-01")
    fused = reciprocal_rank_fusion([a, b], [b, a], limit=2)
    assert len(fused) == 2
    assert {x["citation"] for x in fused} == {a["citation"], b["citation"]}
    assert all(x["hybrid_score"] > 0 for x in fused)


def test_embedding_vector_check():
    assert len(validate_embedding([1.0] * EMBEDDING_DIM)) == EMBEDDING_DIM
    with pytest.raises(ValueError): validate_embedding([0.0] * EMBEDDING_DIM)
    with pytest.raises(ValueError): validate_embedding([float("nan")] * EMBEDDING_DIM)
    with pytest.raises(ValueError): validate_embedding([0.1, 0.2])


def test_vertex_embedder_requires_valid_task_without_api():
    client = MagicMock()
    emb = VertexTextEmbedder("demo-project-123", client=client)
    with pytest.raises(ValueError): emb.embed("documents", task_type="ADMIN")
    client.models.embed_content.assert_not_called()


def test_semantic_no_acl_no_cloud_call():
    client, embedder = FakeBigQuery(), FakeEmbedder()
    retriever = HybridClauseRetriever("demo-project-123", mode="semantic", client=client, embedder=embedder)
    assert retriever.search("vitrage", verified_groups=frozenset(), event_date=DATE, coverage_code="BRIS_GLACE") == []
    assert not client.queries and not embedder.calls


def test_semantic_filters_acl_date_coverage_inside_sql(monkeypatch):
    # Minimal offline stand-in for google-cloud-bigquery (only this test).
    import sys, types
    fake_bq = types.ModuleType("google.cloud.bigquery")
    class Param:
        def __init__(self, name, typ, value):
            self.name, self.type_, self.value = name, typ, value
    class QueryConfig:
        def __init__(self, query_parameters, maximum_bytes_billed):
            self.query_parameters = query_parameters
            self.maximum_bytes_billed = maximum_bytes_billed
    fake_bq.ScalarQueryParameter = Param
    fake_bq.ArrayQueryParameter = Param
    fake_bq.QueryJobConfig = QueryConfig
    cloud = types.ModuleType("google.cloud")
    cloud.bigquery = fake_bq
    monkeypatch.setitem(sys.modules, "google.cloud", cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.bigquery", fake_bq)
    client, embedder = FakeBigQuery([ROW]), FakeEmbedder()
    retriever = HybridClauseRetriever("demo-project-123", mode="semantic", client=client, embedder=embedder)
    assert retriever.search("bris glace", verified_groups=GROUPS, event_date=DATE, coverage_code="BRIS_GLACE")[0]["citation"] == ROW["citation"]
    sql, config, location = client.queries[0]
    assert "UNNEST(allowed_groups)" in sql
    assert "effective_from <= @event_date" in sql and "effective_to >= @event_date" in sql
    assert "coverage_code IN (@coverage_code, 'ALL')" in sql
    assert "COSINE_DISTANCE" in sql
    assert "@query_embedding" in sql
    assert config.maximum_bytes_billed == 100_000_000
    params = {p.name: p.value for p in config.query_parameters if hasattr(p, 'value')}
    assert params["event_date"].isoformat() == DATE
    assert params["coverage_code"] == "BRIS_GLACE"
    assert embedder.calls[0][1] == "RETRIEVAL_QUERY"
    assert location == "europe-west1"


def test_hybrid_semantic_outage_falls_back_to_authorized_lexical():
    lexical = MagicMock()
    lexical.search.return_value = [ROW]
    retriever = HybridClauseRetriever("demo-project-123", mode="hybrid", lexical=lexical, embedder=FakeEmbedder(), client=FakeBigQuery())
    retriever.semantic_search = MagicMock(side_effect=RuntimeError("semantic unavailable"))
    rows = retriever.search("bris glace", verified_groups=GROUPS, event_date=DATE, coverage_code="BRIS_GLACE")
    assert rows == [ROW]
    lexical.search.assert_called_once()


def test_hybrid_does_not_fallback_without_group():
    lexical = MagicMock()
    retriever = HybridClauseRetriever("demo-project-123", mode="hybrid", lexical=lexical)
    assert retriever.search("bris", verified_groups=frozenset(), event_date=DATE) == []
    lexical.search.assert_not_called()


def test_exact_citations_are_not_vector_approximations():
    lexical = MagicMock()
    lexical.fetch_citations.return_value = [{"citation": ROW["citation"]}]
    retriever = HybridClauseRetriever("demo-project-123", mode="hybrid", lexical=lexical)
    assert retriever.fetch_citations([ROW["citation"]], verified_groups=GROUPS, event_date=DATE, coverage_code="BRIS_GLACE") == [{"citation": ROW["citation"]}]
    lexical.fetch_citations.assert_called_once()


def test_gold_metrics_with_acl_failures():
    gold = [
        {"id": "q1", "expected": ["A"], "forbidden": ["X"]},
        {"id": "q2", "expected": ["B"], "forbidden": ["Z"]},
        {"id": "q3", "expected": [], "forbidden": ["SECRET"]},
    ]
    scores = metrics(gold, [["C", "A"], ["C"], []])
    assert scores["hit_at_5"] == 0.5
    assert scores["mrr_at_5"] == 0.25
    assert scores["forbidden_citation_count"] == 0
    assert metrics(gold, [["X"], ["B"], ["SECRET"]])["forbidden_citation_count"] == 2
