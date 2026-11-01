"""Hybrid lexical + semantic retrieval over BigQuery, with server-side ACL.

The existing BigQuery SEARCH/exact-citation retriever remains the source for
contractual proof. A separate, versioned table stores document embeddings.
For the small demo corpus use exact COSINE_DISTANCE after SQL ACL filtering;
VECTOR_SEARCH/indexes are a scaling option, not required here.

No model-generated identity or role is accepted. Disable by default until
benchmark and deployed checks have passed.
"""
from __future__ import annotations

import math
import os
import re
from datetime import date

from .retrieval import BigQueryClauseRetriever, PROJECT_RE, _tokens

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768
EMBEDDING_TABLE = "contract_embeddings_demo"
MODES = frozenset({"lexical", "semantic", "hybrid"})


def validate_embedding(values: list[float], *, dimension: int = EMBEDDING_DIM) -> list[float]:
    """Reject malformed vectors before building SQL or persisting rows."""
    if len(values) != dimension or dimension < 2 or dimension > 3072:
        raise ValueError("Dimension d'embedding incoherente")
    vector = [float(v) for v in values]
    if not all(math.isfinite(v) for v in vector) or not any(v != 0 for v in vector):
        raise ValueError("Embedding invalide")
    return vector


class VertexTextEmbedder:
    """Vertex AI Gemini embeddings; client is lazily initialized for tests."""

    def __init__(self, project: str, *, location: str = "europe-west1", client=None):
        if not PROJECT_RE.fullmatch(project):
            raise ValueError("Projet GCP invalide")
        self.project, self.location, self.client = project, location, client

    def embed(self, text: str, *, task_type: str) -> list[float]:
        """Separate task types for corpus and query; fail rather than truncate."""
        if task_type not in {"RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"}:
            raise ValueError("Type d'embedding inconnu")
        if not 2 <= len(text) <= 6000:
            raise ValueError("Texte hors bornes")
        from google import genai
        from google.genai import types
        if self.client is None:
            self.client = genai.Client(
                vertexai=True, project=self.project, location=self.location,
                http_options=types.HttpOptions(api_version="v1"),
            )
        response = self.client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=EMBEDDING_DIM,
            ),
        )
        values = response.embeddings[0].values if response.embeddings else []
        return validate_embedding(values)


def reciprocal_rank_fusion(lexical: list[dict], semantic: list[dict], *, limit: int = 5, k: int = 60) -> list[dict]:
    """RRF avoids comparing incomparable lexical and cosine scores."""
    if not 1 <= limit <= 20:
        raise ValueError("Limite hors bornes")
    fused: dict[str, dict] = {}
    for name, records in (("lexical", lexical), ("semantic", semantic)):
        for rank, row in enumerate(records, start=1):
            citation = row["citation"]
            if citation not in fused:
                fused[citation] = {**row, "retrieval_mode": name, "hybrid_score": 0.0}
            fused[citation]["hybrid_score"] += 1 / (k + rank)
            if name not in fused[citation]["retrieval_mode"].split("+"):
                fused[citation]["retrieval_mode"] += "+" + name
    return sorted(fused.values(), key=lambda row: (-row["hybrid_score"], row["citation"]))[:limit]


class HybridClauseRetriever:
    """Decorator retaining exact CG evidence lookup and lexical fallback.

    Any failure of the semantic branch is surfaced as a sanitized metric and
    falls back to *already authorized* lexical results. Exact citations needed
    for a coverage conclusion are never replaced by approximate neighbors.
    """
    def __init__(
        self, project: str, *, mode: str = "hybrid", location: str = "europe-west1",
        lexical=None, embedder=None, client=None,
    ):
        if mode not in MODES:
            raise ValueError("Mode RAG invalide")
        if not PROJECT_RE.fullmatch(project):
            raise ValueError("Projet GCP invalide")
        self.project, self.location, self.mode = project, location, mode
        self.lexical = lexical if lexical is not None else BigQueryClauseRetriever(project, location=location)
        self.embedder = embedder if embedder is not None else VertexTextEmbedder(project, location=location)
        self.client = client

    @property
    def table_id(self) -> str:
        return f"{self.project}.autoclaim_mvp.{EMBEDDING_TABLE}"

    def fetch_citations(self, citations: list[str], *, verified_groups: frozenset[str], event_date: str, coverage_code: str | None = None) -> list[dict]:
        # Critical contractual checks continue to use exact ACL/date/coverage.
        return self.lexical.fetch_citations(
            citations, verified_groups=verified_groups, event_date=event_date,
            coverage_code=coverage_code,
        )

    def semantic_search(self, query: str, *, verified_groups: frozenset[str], event_date: str, coverage_code: str | None = None, limit: int = 5) -> list[dict]:
        if not verified_groups:
            return []
        if not 1 <= limit <= 20:
            raise ValueError("Limite invalide")
        if not _tokens(query):
            return []
        when = date.fromisoformat(event_date)
        from google.cloud import bigquery
        client = self.client or bigquery.Client(project=self.project, location=self.location)
        vector = self.embedder.embed(query[:300], task_type="RETRIEVAL_QUERY")
        sql = f"""
            SELECT clause_id, document_id, version, section, title, coverage_code,
                   clause_type, text, citation,
                   COSINE_DISTANCE(embedding, @query_embedding) AS distance
            FROM `{self.table_id}`
            WHERE embedding_model = @embedding_model
              AND embedding_dimensions = @dimensions
              AND effective_from <= @event_date AND effective_to >= @event_date
              AND EXISTS (
                SELECT 1 FROM UNNEST(allowed_groups) AS allowed_group
                WHERE allowed_group IN UNNEST(@verified_groups)
              )
              AND (@coverage_code = '' OR coverage_code IN (@coverage_code, 'ALL'))
            ORDER BY distance ASC, citation ASC LIMIT @candidate_limit
        """
        config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("query_embedding", "FLOAT64", vector),
                bigquery.ScalarQueryParameter("embedding_model", "STRING", EMBEDDING_MODEL),
                bigquery.ScalarQueryParameter("dimensions", "INT64", EMBEDDING_DIM),
                bigquery.ScalarQueryParameter("event_date", "DATE", when),
                bigquery.ArrayQueryParameter("verified_groups", "STRING", sorted(verified_groups)),
                bigquery.ScalarQueryParameter("coverage_code", "STRING", coverage_code or ""),
                bigquery.ScalarQueryParameter("candidate_limit", "INT64", min(50, max(20, limit * 5))),
            ],
            maximum_bytes_billed=100_000_000,
        )
        job = client.query(sql, job_config=config, location=self.location)
        return [dict(row.items()) for row in job.result(timeout=60)]

    def search(self, query: str, *, verified_groups: frozenset[str], event_date: str, coverage_code: str | None = None, limit: int = 5) -> list[dict]:
        if not verified_groups:
            return []
        if self.mode == "lexical":
            return self.lexical.search(query, verified_groups=verified_groups, event_date=event_date, coverage_code=coverage_code, limit=limit)
        # Preserve a lexical result in hybrid mode if vector dependency fails.
        lex = self.lexical.search(query, verified_groups=verified_groups, event_date=event_date, coverage_code=coverage_code, limit=max(5, limit * 3)) if self.mode == "hybrid" else []
        try:
            sem = self.semantic_search(query, verified_groups=verified_groups, event_date=event_date, coverage_code=coverage_code, limit=max(5, limit * 3))
        except Exception:
            if self.mode == "semantic":
                raise   # No unauthorized or synthetic semantic results.
            from autoclaim_api.observability import log_retrieval
            log_retrieval("lexical_fallback", len(lex))
            return lex[:limit]
        from autoclaim_api.observability import log_retrieval
        if self.mode == "semantic":
            log_retrieval("semantic", len(sem))
            return sem[:limit]
        fused = reciprocal_rank_fusion(lex, sem, limit=limit)
        log_retrieval("hybrid", len(fused))
        return fused
