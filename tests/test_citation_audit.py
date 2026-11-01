"""Lot 8: exact source reconciliation, record-vs-PDF provenance and ACLs.

Everything is tested offline. The BigQuery adapter is replaced with the local
retriever, but it has the same interface including exact citation lookups.
"""

import json

import pytest
from fastapi.testclient import TestClient

from autoclaim_agent.retrieval import LocalClauseRetriever
from autoclaim_agent.repository import find_claim
from autoclaim_agent.security import VerifiedPrincipal
from autoclaim_agent.tools import create_tools
from autoclaim_api.app import build_app
from autoclaim_api.citation_audit import (
    CitationAudit, SAFE_ANSWER, NO_SOURCE_ANSWER,
    audit_chat_answer, extract_citations,
)
from autoclaim_api.iap_auth import AuthenticatedUser, InvalidIdentity
from autoclaim_api.observability import log_citation_audit
from autoclaim_api.roles import resolve_groups

MANAGER = VerifiedPrincipal("manager", frozenset({"gestionnaires_auto"}))
SUPERVISOR = VerifiedPrincipal("supervisor", frozenset({"superviseurs_auto"}))


def audit(answer, claim_id="SIN-1001", principal=MANAGER, query="facture", matches=None):
    retriever = LocalClauseRetriever(include_documents=True)
    review, search = create_tools(principal, retriever)
    preflight = review(claim_id)
    if matches is None:
        matches = search(claim_id, query)
    return audit_chat_answer(
        answer,
        claim=find_claim(claim_id),
        principal=principal,
        retriever=retriever,
        preflight=preflight,
        matches=matches,
    )


def test_exact_citations_extracted_in_order_and_deduplicated():
    response = (
        "Voir `DOC-GUIDE-BG-2026@v1.0#P001-01`, "
        "CG-AUTO-DEMO-2026@v1.0#DEC-01 et DOC-GUIDE-BG-2026@v1.0#P001-01."
    )
    assert extract_citations(response) == [
        "DOC-GUIDE-BG-2026@v1.0#P001-01",
        "CG-AUTO-DEMO-2026@v1.0#DEC-01",
    ]


def test_pdf_source_verified_and_only_cited_is_returned():
    result = audit("Pieces selon DOC-GUIDE-BG-2026@v1.0#P001-01.", query="devis photos")
    assert result.status == "VERIFIED_CITATIONS"
    assert [r["citation"] for r in result.sources] == ["DOC-GUIDE-BG-2026@v1.0#P001-01"]
    assert result.sources[0]["document_id"] == "DOC-GUIDE-BG-2026"
    assert result.sources[0]["origin"] == "DOCUMENT_PDF_DOCX"


def test_valid_declared_citation_can_be_retrieved_exactly_if_not_in_search_hits():
    result = audit(
        "Delais : CG-AUTO-DEMO-2026@v1.0#DEC-01",
        query="facture",
        matches={"clauses": []},
    )
    assert result.status == "VERIFIED_CITATIONS"
    assert [r["citation"] for r in result.sources] == ["CG-AUTO-DEMO-2026@v1.0#DEC-01"]


def test_cp_source_from_verified_preflight_is_accepted():
    result = audit("Franchise: CP-POL-AUTO-001@v1.0#BRIS_GLACE")
    assert result.status == "VERIFIED_CITATIONS"
    assert result.sources[0]["origin"] == "SI_FICTIF"


def test_missing_coverage_cp_can_be_verified_as_structured_absence():
    result = audit("Pas de garantie : CP-POL-AUTO-002@v1.0", claim_id="SIN-1002")
    assert result.status == "VERIFIED_CITATIONS"
    assert result.sources[0]["origin"] == "SI_FICTIF"
    assert "ne figure pas" in result.sources[0]["excerpt"]


def test_cross_coverage_reference_is_rejected():
    result = audit(
        "CG-AUTO-DEMO-2026@v1.0#VOL-01", matches={"clauses": []}
    )
    assert result.status == "BLOCKED_UNVERIFIED_CITATION"
    assert result.answer == SAFE_ANSWER and result.sources == []


def test_unknown_citation_blocks_entire_model_answer_and_does_not_echo_id():
    ref = "CG-FAKE-2026@v1.0#SECRET-01"
    result = audit(f"La source {ref} certifie le paiement.", matches={"clauses": []})
    assert result.status == "BLOCKED_UNVERIFIED_CITATION"
    assert result.answer == SAFE_ANSWER
    assert ref not in result.answer and result.sources == []


def test_sensitive_document_cannot_be_cited_by_manager_even_with_fake_search_hit():
    sensitive = "DOC-CONTROLE-SENSIBLE-2026@v1.0#S001-01"
    bogus_match = {
        "citation": sensitive, "document_id": "DOC-CONTROLE-SENSIBLE-2026",
        "coverage_code": "ALL", "title": "Note de supervision", "text": "INTERNAL",
    }
    result = audit(f"Selon {sensitive}, details sensibles.", matches={"clauses": [bogus_match]})
    assert result.status == "BLOCKED_UNVERIFIED_CITATION"
    assert result.sources == []
    assert "details sensibles" not in result.answer


def test_sensitive_document_allowed_for_supervisor_if_exact_source_exists():
    result = audit(
        "Note : DOC-CONTROLE-SENSIBLE-2026@v1.0#S001-01",
        principal=SUPERVISOR, matches={"clauses": []},
    )
    assert result.status == "VERIFIED_CITATIONS"
    assert result.sources[0]["document_id"] == "DOC-CONTROLE-SENSIBLE-2026"


def test_bare_unauthorized_document_id_blocks_answer_even_if_other_citation_valid():
    result = audit(
        "Source : CG-AUTO-DEMO-2026@v1.0#BG-01. "
        "Mais consultez DOC-CONTROLE-SENSIBLE-2026 en prive."
    )
    assert result.status == "BLOCKED_UNVERIFIED_CITATION"
    assert result.sources == []


def test_missing_citation_returns_non_factual_fallback():
    result = audit("Le modele affirme un paiement de 1 million.")
    assert result.status == "NO_CITATIONS"
    assert result.sources == [] and result.answer == NO_SOURCE_ANSWER


def test_retriever_filters_exact_citations_by_coverage():
    retriever = LocalClauseRetriever(include_documents=True)
    # Both rows exist, but a BRIS_GLACE claim cannot cite the VOL guarantee.
    assert retriever.fetch_citations(
        ["CG-AUTO-DEMO-2026@v1.0#VOL-01"],
        verified_groups=MANAGER.groups,
        event_date="2026-10-30",
        coverage_code="BRIS_GLACE",
    ) == []


def test_citation_log_excludes_document_ids_claim_ids_and_answers(capsys):
    log_citation_audit("BLOCKED_UNVERIFIED_CITATION", 0)
    event = json.loads(capsys.readouterr().out)
    assert event["event"] == "citation_audit"
    assert event["outcome"] == "BLOCKED_UNVERIFIED_CITATION"
    assert "claim_id" not in event and "citation" not in event


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTOCLAIM_IAP_AUDIENCE", "aud")
    monkeypatch.setenv("AUTOCLAIM_MANAGER_EMAILS", "manager@example.com")
    monkeypatch.setenv("AUTOCLAIM_SUPERVISOR_EMAILS", "supervisor@example.com")

    def verifier(token, aud):
        if token == "manager":
            return AuthenticatedUser("sub", "manager@example.com")
        raise InvalidIdentity("bad token")

    return TestClient(build_app(
        verifier=verifier, role_resolver=resolve_groups,
        retriever_factory=lambda: LocalClauseRetriever(include_documents=True),
    ))


def test_chat_endpoint_only_returns_sources_mentioned_in_gemini_text(client, monkeypatch):
    async def answer(*args, **kwargs):
        return "Justificatifs dans DOC-GUIDE-BG-2026@v1.0#P001-01."
    monkeypatch.setattr("autoclaim_api.app.answer_with_adk", answer)
    res = client.post("/api/claims/SIN-1001/chat", headers={"X-Goog-IAP-JWT-Assertion": "manager"},
                      json={"question": "Quels justificatifs fournir ?"})
    assert res.status_code == 200
    data = res.json()
    assert data["grounding_status"] == "VERIFIED_CITATIONS"
    assert len(data["sources"]) == 1
    assert data["sources"][0]["citation"] == "DOC-GUIDE-BG-2026@v1.0#P001-01"


def test_chat_endpoint_returns_safe_fallback_for_unverified_model_source(client, monkeypatch):
    async def answer(*args, **kwargs):
        return "Secret de la note DOC-CONTROLE-SENSIBLE-2026@v1.0#S001-01"
    monkeypatch.setattr("autoclaim_api.app.answer_with_adk", answer)
    res = client.post("/api/claims/SIN-1001/chat", headers={"X-Goog-IAP-JWT-Assertion": "manager"},
                      json={"question": "Quelle est la note interne ?"})
    assert res.status_code == 200
    data = res.json()
    assert data["grounding_status"] == "BLOCKED_UNVERIFIED_CITATION"
    assert data["answer"] == SAFE_ANSWER and data["sources"] == []
    assert "DOC-CONTROLE-SENSIBLE" not in res.text


def test_original_sin1002_mismatch_regression_only_cited_sources_returned():
    """Reproduce the user's mismatched DEC vs CALC source list."""
    answer = (
        "Garantie non souscrite : CP-POL-AUTO-002@v1.0. "
        "Declaration tardive : CG-AUTO-DEMO-2026@v1.0#DEC-01. "
        "Procedure : DOC-PROCEDURE-AUTO-2026@v1.0#S001-01."
    )
    result = audit(answer, claim_id="SIN-1002", query="calcul franchise")
    assert result.status == "VERIFIED_CITATIONS"
    assert [s["citation"] for s in result.sources] == [
        "CP-POL-AUTO-002@v1.0",
        "CG-AUTO-DEMO-2026@v1.0#DEC-01",
        "DOC-PROCEDURE-AUTO-2026@v1.0#S001-01",
    ]
    assert all("#CALC-01" not in s["citation"] for s in result.sources)
    assert result.sources[0]["origin"] == "SI_FICTIF"
    assert result.sources[-1]["origin"] == "DOCUMENT_PDF_DOCX"


def test_bigquery_exact_lookup_sql_checks_coverage_as_well_as_acl(monkeypatch):
    import sys
    from types import SimpleNamespace, ModuleType
    from unittest.mock import MagicMock
    from autoclaim_agent.retrieval import BigQueryClauseRetriever

    fake = ModuleType("google.cloud.bigquery")
    fake.ArrayQueryParameter = lambda name, kind, value: SimpleNamespace(name=name, value=value)
    fake.ScalarQueryParameter = fake.ArrayQueryParameter
    fake.QueryJobConfig = lambda **kw: SimpleNamespace(**kw)
    cloud = ModuleType("google.cloud")
    cloud.bigquery = fake
    monkeypatch.setitem(sys.modules, "google.cloud", cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.bigquery", fake)
    bq_client = MagicMock()
    bq_client.query.return_value.result.return_value = []
    retriever = BigQueryClauseRetriever("demo-project-123", client=bq_client)
    retriever.fetch_citations(
        ["CG-AUTO-DEMO-2026@v1.0#DEC-01"],
        verified_groups=MANAGER.groups,
        event_date="2026-10-30",
        coverage_code="BRIS_GLACE",
    )
    sql = bq_client.query.call_args.args[0]
    assert "coverage_code IN (@coverage_code, 'ALL')" in sql
    assert "UNNEST(allowed_groups)" in sql
    args = bq_client.query.call_args.kwargs["job_config"].query_parameters
    assert {p.name: p.value for p in args}["coverage_code"] == "BRIS_GLACE"
