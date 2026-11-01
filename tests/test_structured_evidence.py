"""Preuve des franchises/plafonds par le SI, sans appels Gemini/BigQuery."""

from unittest.mock import patch

from autoclaim_agent.repository import find_claim
from autoclaim_agent.retrieval import LocalClauseRetriever
from autoclaim_agent.security import VerifiedPrincipal
from autoclaim_agent.structured_evidence import resolve_structured_evidence
from autoclaim_agent.tools import create_tools

MANAGER = VerifiedPrincipal("manager-demo", frozenset({"gestionnaires_auto"}))
SUPERVISOR = VerifiedPrincipal("supervisor-demo", frozenset({"superviseurs_auto"}))


def review(claim_id, principal=MANAGER):
    tool, _ = create_tools(principal, LocalClauseRetriever())
    return tool(claim_id)


def test_all_source_refs_are_now_backed_by_an_evidence_record():
    result = review("SIN-1001")
    assert result["status"] == "COVERED_IN_PRINCIPLE"
    assert set(result["source_refs"]) == {
        proof["citation"] for proof in result["contractual_evidence"]
    }


def test_cp_structured_record_proves_initial_franchise_and_limit():
    result = review("SIN-1001")
    cp = next(
        proof for proof in result["contractual_evidence"]
        if proof["citation"] == "CP-POL-AUTO-001@v1.0#BRIS_GLACE"
    )
    assert cp["source_system"] == "SI_FICTIF"
    assert cp["evidence_type"] == "structured_policy_record"
    assert cp["data"]["deductible_eur"] == 80
    assert cp["data"]["limit_eur"] == 1200
    assert "original n'a pas ete consulte" in cp["text"]


def test_avenant_is_traced_without_overwriting_original_cp():
    result = review("SIN-1005")
    assert result["status"] == "COVERED_IN_PRINCIPLE"
    assert result["indicative_amount_eur"] == 9400
    cp = next(p for p in result["contractual_evidence"] if p["citation"].startswith("CP-"))
    av = next(p for p in result["contractual_evidence"] if p["citation"].startswith("AV-"))
    assert cp["data"]["limit_eur"] == 8000
    assert av["data"]["changes"]["limit_eur"] == 10000
    assert av["data"]["effective_from"] == "2026-10-15"
    assert set(result["source_refs"]) == {p["citation"] for p in result["contractual_evidence"]}


def test_potential_decheance_has_contract_and_cg_proof():
    result = review("SIN-1004", SUPERVISOR)
    assert result["status"] == "DECHANCE_REVIEW"
    assert "indicative_amount_eur" not in result
    assert set(result["source_refs"]) == {p["citation"] for p in result["contractual_evidence"]}


def test_source_repository_unavailable_blocks_positive_conclusion():
    # Simuler une disparition de la CP alors que le calcul preliminaire a eu lieu.
    with patch("autoclaim_agent.structured_evidence.find_policy", return_value=None):
        result = review("SIN-1001")
    assert result["status"] == "EVIDENCE_INCOMPLETE"
    assert "CP-POL-AUTO-001@v1.0#BRIS_GLACE" in result["missing_citations"]
    assert "indicative_amount_eur" not in result


def test_structured_source_cannot_be_requested_for_other_contract():
    claim = find_claim("SIN-1001")
    result = resolve_structured_evidence(
        claim,
        ["CP-POL-AUTO-002@v1.0#BRIS_GLACE", "AV-001@v1.0#DTA"],
    )
    assert result == []


def test_manager_still_cannot_access_restricted_claim():
    result = review("SIN-1004", MANAGER)
    assert result["status"] == "NOT_ACCESSIBLE"
    assert "contractual_evidence" not in result
