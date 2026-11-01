"""Controles de l'observabilite sans service GCP ni appel Gemini."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from autoclaim_agent.retrieval import LocalClauseRetriever
from autoclaim_api.app import build_app
from autoclaim_api.iap_auth import AuthenticatedUser, InvalidIdentity
from autoclaim_api.observability import (
    log_coverage_review, log_http, log_llm_call,
)
from autoclaim_api.roles import resolve_groups

AUDIENCE = "/projects/123/locations/europe-west1/services/demo"


def _events(captured):
    """Ne lire que les lignes JSON structurees du journal stdout."""
    return [json.loads(line) for line in captured.splitlines() if line.startswith("{")]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTOCLAIM_IAP_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("AUTOCLAIM_MANAGER_EMAILS", "gestionnaire@example.com")
    monkeypatch.setenv("AUTOCLAIM_SUPERVISOR_EMAILS", "superviseur@example.com")

    def verifier(token, audience):
        assert audience == AUDIENCE
        if token == "manager-token":
            return AuthenticatedUser("sub-manager", "gestionnaire@example.com")
        raise InvalidIdentity("invalid")

    return TestClient(build_app(
        verifier=verifier,
        role_resolver=resolve_groups,
        retriever_factory=LocalClauseRetriever,
    ))


def test_http_log_uses_route_template_not_claim_identifier(capsys):
    route = SimpleNamespace(path="/api/claims/{claim_id}/review")
    log_http(route, "GET", 200, 12.8)
    events = _events(capsys.readouterr().out)
    assert events[0]["event"] == "http_request"
    assert events[0]["operation"] == "/api/claims/{claim_id}/review"
    assert events[0]["duration_ms"] == 12.8


def test_unknown_path_is_not_echoed(capsys):
    log_http(SimpleNamespace(path="/api/claims/SIN-SECRET/review"), "GET", 404, 3.2)
    text = capsys.readouterr().out
    assert "SIN-SECRET" not in text
    assert _events(text)[0]["operation"] == "unmatched"


def test_coverage_logging_sanitizes_untrusted_fields(capsys):
    log_coverage_review({
        "status": "COVERED_IN_PRINCIPLE",
        "evidence_origin": "BIGQUERY_ET_SI_FICTIF",
        "claim_id": "SIN-SENSITIVE",
        "email": "secret@example.com",
        "contractual_evidence": [{"text": "private document"}],
        "human_validation_required": True,
    })
    text = capsys.readouterr().out
    event = _events(text)[0]
    assert event["outcome"] == "COVERED_IN_PRINCIPLE"
    assert event["evidence_origin"] == "BIGQUERY_ET_SI_FICTIF"
    assert "SIN-SENSITIVE" not in text
    assert "secret@example.com" not in text
    assert "private document" not in text


def test_unknown_business_status_not_logged_verbatim(capsys):
    log_coverage_review({"status": "SIN-PRIVATE", "evidence_origin": "email@example.com"})
    event = _events(capsys.readouterr().out)[0]
    assert event["outcome"] == "OTHER"
    assert event["evidence_origin"] == "UNSPECIFIED"


def test_llm_telemetry_has_no_prompts(capsys):
    log_llm_call(True, 50.44)
    event = _events(capsys.readouterr().out)[0]
    assert event["event"] == "llm_call"
    assert event["outcome"] == "success"
    assert event["duration_ms"] == 50.4


def test_denied_claim_logs_404_without_claim_id(client, capsys):
    response = client.get(
        "/api/claims/SIN-1004/review",
        headers={
            "X-Goog-IAP-JWT-Assertion": "manager-token",
            "X-Custom-Token": "SUPER-SECRET-HEADER",
        },
    )
    assert response.status_code == 404
    output = capsys.readouterr().out
    http_events = [r for r in _events(output) if r.get("event") == "http_request"]
    assert http_events
    assert http_events[-1]["status_code"] == 404
    assert http_events[-1]["operation"] == "/api/claims/{claim_id}/review"
    assert "SIN-1004" not in output
    assert "SUPER-SECRET-HEADER" not in output
    assert "gestionnaire@example.com" not in output


def test_review_logs_status_without_amounts_or_claim_id(client, capsys):
    response = client.get(
        "/api/claims/SIN-1001/review",
        headers={"X-Goog-IAP-JWT-Assertion": "manager-token"},
    )
    assert response.status_code == 200
    output = capsys.readouterr().out
    events = _events(output)
    business = [r for r in events if r.get("event") == "coverage_review"]
    assert business and business[-1]["outcome"] == "COVERED_IN_PRINCIPLE"
    assert "SIN-1001" not in output
    assert "POL-AUTO" not in output
    assert "gestionnaire@example.com" not in output
