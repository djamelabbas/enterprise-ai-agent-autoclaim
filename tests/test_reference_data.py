"""Tests du referentiel fictif : aucune connexion externe ni cle API."""

from pathlib import Path
import json

import pytest

from autoclaim_agent.coverage import analyze_coverage
from autoclaim_agent.repository import (
    authorized_clauses,
    effective_terms,
    find_policy,
    list_claims,
    list_clauses,
    list_endorsements,
    list_policies,
)

ROOT = Path(__file__).resolve().parents[1]
ANALYST = frozenset({"gestionnaires_auto"})
SUPERVISOR = frozenset({"superviseurs_auto"})


@pytest.mark.parametrize("case", json.loads((ROOT / "data/expected_cases.json").read_text(encoding="utf-8")))
def test_expected_business_scenarios(case):
    # Le dossier sensible SIN-1004 est reserve aux superviseurs.
    groups = SUPERVISOR if case["claim_id"] == "SIN-1004" else ANALYST
    result = analyze_coverage(case["claim_id"], verified_groups=groups)
    assert result["status"] == case["expected_status"]
    if case["expected_indicative_amount_eur"] is not None:
        assert result["indicative_amount_eur"] == case["expected_indicative_amount_eur"]
        assert result["human_validation_required"] is True
    else:
        assert "indicative_amount_eur" not in result


def test_analyst_cannot_access_supervisor_claim():
    denied = analyze_coverage("SIN-1004", verified_groups=ANALYST)
    unknown = analyze_coverage("SIN-9999", verified_groups=ANALYST)
    assert denied == unknown == {"status": "NOT_ACCESSIBLE", "message": "Dossier introuvable ou non autorise."}


def test_anonymous_user_cannot_access_claim():
    assert analyze_coverage("SIN-1001", verified_groups=frozenset())["status"] == "NOT_ACCESSIBLE"


def test_authorized_group_does_not_see_confidential_clause():
    analyst_refs = {c["clause_id"] for c in authorized_clauses(ANALYST, "2026-10-20")}
    supervisor_refs = {c["clause_id"] for c in authorized_clauses(SUPERVISOR, "2026-10-20")}
    assert "CONF-01" not in analyst_refs
    assert "CONF-01" in supervisor_refs


def test_endorsement_is_effective_only_from_its_start_date():
    policy = find_policy("POL-AUTO-001")
    before = effective_terms(policy, "DTA", "2026-10-14")
    after = effective_terms(policy, "DTA", "2026-10-15")
    assert before["limit_eur"] == 8000
    assert after["limit_eur"] == 10000
    assert "AV-001@v1.0#DTA" not in before["sources"]
    assert "AV-001@v1.0#DTA" in after["sources"]


def test_all_claims_reference_existing_policies_and_coverages():
    policy_ids = {p["policy_id"] for p in list_policies()}
    coverage_codes = {"BRIS_GLACE", "VOL", "DTA"}
    assert len(list_claims()) == 8
    for claim in list_claims():
        assert claim["policy_id"] in policy_ids
        assert claim["coverage_code"] in coverage_codes
        assert claim["damage_eur"] >= 0
    for amendment in list_endorsements():
        assert amendment["policy_id"] in policy_ids
        assert amendment["coverage_code"] in coverage_codes


def test_clauses_have_stable_unique_citations():
    citations = [c["citation"] for c in list_clauses()]
    assert len(citations) == len(set(citations))
    assert all(c["allowed_groups"] for c in list_clauses())


def test_eligibility_does_not_imply_auto_indemnification():
    result = analyze_coverage("SIN-1001", verified_groups=ANALYST)
    assert result["status"] == "COVERED_IN_PRINCIPLE"
    assert result["human_validation_required"] is True
    assert result["source_refs"]
