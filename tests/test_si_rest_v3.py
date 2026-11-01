"""P2: no IAM bypass; REST is read-only and authenticated."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autoclaim_agent.si_rest import CloudRunSIConnector, SIUnavailable, ensure_consistent, validate_service_url
from si_mock_api.main import app

URL = "https://si-demo-123456.europe-west1.run.app"
LOCAL = {"claim_id":"SIN-1001", "policy_id":"POL-AUTO-001", "event_date":"2026-10-30",
         "coverage_code":"BRIS_GLACE", "damage_eur":600,
         "received_documents":["devis_reparation"], "description":"Demo"}


def test_url_validation_prevents_ssrf():
    assert validate_service_url(URL) == URL
    for url in ["http://si-demo.run.app", "https://localhost", "https://evil.org", "https://si.run.app.evil.com", URL + "/admin", URL+"?secret=x", "http://169.254.169.254"]:
        with pytest.raises(ValueError): validate_service_url(url)


def test_connector_signed_id_token_and_strict_claim_path():
    requests = []
    def request(url, token):
        requests.append((url,token))
        return dict(LOCAL)
    conn = CloudRunSIConnector(URL, token_factory=lambda aud: "signed:"+aud, get_json=request)
    assert conn.get_claim("SIN-1001")["claim_id"] == "SIN-1001"
    assert requests == [(URL+"/v1/claims/SIN-1001", "signed:"+URL)]
    with pytest.raises(ValueError): conn.get_claim("../secrets")


def test_connector_rejects_cross_claim_payload():
    conn = CloudRunSIConnector(URL, token_factory=lambda _: "token", get_json=lambda *_: dict(LOCAL, claim_id="SIN-1004"))
    with pytest.raises(SIUnavailable): conn.get_claim("SIN-1001")


def test_connector_does_not_fallback_on_network_failure():
    conn = CloudRunSIConnector(URL, token_factory=lambda _: "token", get_json=lambda *_: (_ for _ in ()).throw(ConnectionError("outage")))
    with pytest.raises(SIUnavailable): conn.get_claim("SIN-1001")


def test_rest_and_local_must_match():
    assert ensure_consistent(LOCAL, dict(LOCAL))["coverage_code"] == "BRIS_GLACE"
    with pytest.raises(SIUnavailable): ensure_consistent(LOCAL, dict(LOCAL, damage_eur=123))
    with pytest.raises(SIUnavailable): ensure_consistent(LOCAL, dict(LOCAL, received_documents=[]))


def test_separate_si_mock_api_contract():
    client = TestClient(app)
    assert client.get("/v1/claims/SIN-1001").status_code == 200
    obj = client.get("/v1/claims/SIN-1001").json()
    assert obj["policy_id"] == "POL-AUTO-001"
    assert "authorized_groups" not in obj and "flags" not in obj
    assert client.get("/v1/claims/SIN-9999").status_code == 404


def test_business_endpoint_refuses_manager_without_network(monkeypatch):
    from autoclaim_api.app import build_app
    from autoclaim_api.iap_auth import AuthenticatedUser
    from autoclaim_agent.retrieval import LocalClauseRetriever
    monkeypatch.setenv("AUTOCLAIM_IAP_AUDIENCE", "test-audience")
    monkeypatch.setenv("AUTOCLAIM_MANAGER_EMAILS", "manager@example.com")
    def verifier(*_): return AuthenticatedUser("sub", "manager@example.com")
    client = TestClient(build_app(verifier=verifier, retriever_factory=LocalClauseRetriever))
    r = client.get("/api/claims/SIN-1004/si-check")
    assert r.status_code == 404
    assert "SIN-1004" not in r.text


def test_disabled_rest_is_not_silently_accepted(monkeypatch):
    from autoclaim_agent.si_rest import make_si_connector
    monkeypatch.setenv("AUTOCLAIM_SI_MODE", "local")
    with pytest.raises(SIUnavailable): make_si_connector()
