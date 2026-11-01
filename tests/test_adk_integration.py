"""Tests d'integration des outils ADK SANS Gemini ni appel GCP."""

from inspect import signature
from unittest.mock import MagicMock

import pytest

from autoclaim_agent.agent import create_agent, root_agent
from autoclaim_agent.retrieval import LocalClauseRetriever
from autoclaim_agent.security import ANONYMOUS, VerifiedPrincipal
from autoclaim_agent.tools import create_tools

ANALYST = VerifiedPrincipal("analyst-1", frozenset({"gestionnaires_auto"}))
SUPERVISOR = VerifiedPrincipal("supervisor-1", frozenset({"superviseurs_auto"}))


def test_adk_agent_exposes_two_tools():
    agent = create_agent(ANALYST, LocalClauseRetriever())
    assert agent.name == "autoclaim_coverage_agent"
    assert len(agent.tools) == 2


def test_root_agent_is_anonymous_and_denied():
    assert len(root_agent.tools) == 2
    assert root_agent.tools[0]("SIN-1001")["status"] == "NOT_ACCESSIBLE"


def test_model_cannot_supply_role_or_groups():
    review, search = create_tools(ANALYST, LocalClauseRetriever())
    assert tuple(signature(review).parameters) == ("claim_id",)
    assert tuple(signature(search).parameters) == ("claim_id", "query")


def test_expected_positive_case_has_verified_cg_evidence():
    review, _ = create_tools(ANALYST, LocalClauseRetriever())
    result = review("SIN-1001")
    assert result["status"] == "COVERED_IN_PRINCIPLE"
    assert result["indicative_amount_eur"] == 520
    assert result["human_validation_required"] is True
    citations = {row["citation"] for row in result["contractual_evidence"]}
    assert "CG-AUTO-DEMO-2026@v1.0#BG-01" in citations
    assert "CG-AUTO-DEMO-2026@v1.0#CALC-01" in citations


def test_anonymous_does_not_touch_retriever():
    retriever = MagicMock()
    review, search = create_tools(ANONYMOUS, retriever)
    assert review("SIN-1001")["status"] == "NOT_ACCESSIBLE"
    assert search("SIN-1001", "bris glace")["status"] == "NOT_ACCESSIBLE"
    retriever.search.assert_not_called()
    retriever.fetch_citations.assert_not_called()


def test_analyst_cannot_access_supervisor_claim():
    review, search = create_tools(ANALYST, LocalClauseRetriever())
    assert review("SIN-1004")["status"] == "NOT_ACCESSIBLE"
    assert search("SIN-1004", "declaration tardive")["status"] == "NOT_ACCESSIBLE"


def test_supervisor_can_access_sensitive_claim_with_review_status():
    review, _ = create_tools(SUPERVISOR, LocalClauseRetriever())
    result = review("SIN-1004")
    assert result["status"] == "DECHANCE_REVIEW"
    assert "CG-AUTO-DEMO-2026@v1.0#DEC-01" in {
        row["citation"] for row in result["contractual_evidence"]
    }
    assert "indicative_amount_eur" not in result


def test_unauthorized_clause_not_returned_by_search():
    _, search = create_tools(ANALYST, LocalClauseRetriever())
    result = search("SIN-1001", "note interne supervision")
    assert all(row["clause_id"] != "CONF-01" for row in result["clauses"])


def test_missing_bigquery_evidence_blocks_positive_decision():
    retriever = MagicMock()
    retriever.fetch_citations.return_value = []
    review, _ = create_tools(ANALYST, retriever)
    result = review("SIN-1001")
    assert result["status"] == "EVIDENCE_INCOMPLETE"
    assert "indicative_amount_eur" not in result
    assert result["human_validation_required"] is True


def test_bigquery_outage_blocks_positive_decision():
    retriever = MagicMock()
    retriever.fetch_citations.side_effect = RuntimeError("simulated outage")
    review, _ = create_tools(ANALYST, retriever)
    result = review("SIN-1001")
    assert result["status"] == "EVIDENCE_UNAVAILABLE"
    assert "indicative_amount_eur" not in result


def test_anonymity_rejects_groups_without_subject():
    with pytest.raises(ValueError):
        VerifiedPrincipal("", frozenset({"gestionnaires_auto"}))


def test_exact_lookup_does_not_return_other_group_clauses():
    retriever = LocalClauseRetriever()
    confidential = ["CG-AUTO-DEMO-2026@v1.0#CONF-01"]
    assert retriever.fetch_citations(confidential, verified_groups=ANALYST.groups, event_date="2026-10-20") == []
    assert len(retriever.fetch_citations(confidential, verified_groups=SUPERVISOR.groups, event_date="2026-10-20")) == 1


def test_exact_lookup_does_not_return_expired_clauses():
    retriever = LocalClauseRetriever()
    refs = ["CG-AUTO-DEMO-2026@v1.0#BG-01"]
    assert retriever.fetch_citations(refs, verified_groups=ANALYST.groups, event_date="2027-01-01") == []
